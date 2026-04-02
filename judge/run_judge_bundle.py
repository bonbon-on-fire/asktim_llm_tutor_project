"""Unified bundle judge (GPT + Claude)."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from judge.run_judge import (
    DEFAULT_CLAUDE_MODEL,
    DEFAULT_OPENAI_MODEL,
    DEFAULT_REASONING,
    JudgeError,
    JudgeResult,
    _coerce_int,
    _create_judge_graph,
    _create_model_invoke,
    _env_truthy,
    _format_conversation_for_judge,
    _order_grade_payload,
    _require_anthropic_api_key,
    _require_openai_api_key,
    _sanitize_text,
    load_judge_prompt,
)

Provider = Literal["gpt", "claude"]

TRANSCRIPTS_DIR = REPO_ROOT / "transcripts"
# Keep bundle transcript labels aligned with judge prompt wording.
BUNDLE_TRANSCRIPT_LABEL_TEMPLATE = "TRANSCRIPT {index} OF {total}"


def _parse_bundle_file(bundle_file_path: Path) -> list[str]:
    """Read bundle .txt and return normalized transcript stems (no extension)."""

    if not bundle_file_path.exists():
        raise JudgeError(f"Bundle file not found: {bundle_file_path}")
    stems: list[str] = []
    for line in bundle_file_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        stems.append(s.replace("\\", "/"))
    if not stems:
        raise JudgeError(f"No transcript paths in bundle file: {bundle_file_path}")
    return stems


def _load_transcripts(stems: list[str]) -> list[tuple[str, dict[str, Any]]]:
    """Load and validate transcript JSON docs referenced by bundle stems."""

    rows: list[tuple[str, dict[str, Any]]] = []
    for stem in stems:
        path = TRANSCRIPTS_DIR / f"{stem}.json"
        if not path.exists():
            raise JudgeError(f"Transcript not found: {path}")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise JudgeError(f"Invalid transcript JSON: {path}: {e}") from e
        if not isinstance(data, dict):
            raise JudgeError(f"Transcript must be an object: {path}")
        ex = data.get("exchanges")
        if not isinstance(ex, list) or not ex:
            raise JudgeError(f"Transcript must have non-empty exchanges: {path}")
        rows.append((stem, data))
    return rows


def _format_bundle_conversation(transcripts: list[tuple[str, dict[str, Any]]]) -> tuple[str, int]:
    """Compose multi-transcript judge input text plus total turn count."""

    parts: list[str] = []
    total_turns = 0
    count = len(transcripts)
    for idx, (stem, data) in enumerate(transcripts, start=1):
        persona = _sanitize_text(data.get("student_persona")).strip() or "unknown"
        course = _sanitize_text(data.get("course")).strip() or "unknown"
        exercise = _sanitize_text(data.get("exercise_number")).strip() or "?"
        turns = _coerce_int(data.get("turns"), default=len(data.get("exchanges", [])))
        total_turns += turns
        parts.append(
            "\n".join(
                [
                    "=" * 60,
                    BUNDLE_TRANSCRIPT_LABEL_TEMPLATE.format(index=idx, total=count),
                    "=" * 60,
                    f"Stem: {stem}",
                    f"Persona: {persona}",
                    f"Course: {course}",
                    f"Exercise: {exercise}",
                    "",
                ]
            )
        )
        parts.append(_format_conversation_for_judge(data))
        parts.append("")
    return "\n".join(parts).strip(), total_turns


def judge_transcript_bundle(
    bundle_file_path: str,
    *,
    provider: Provider,
    prompt_name: str = "judge_05",
    rubric_name: str = "rubric_05",
    output_path: str | None = None,
) -> JudgeResult:
    """Judge all transcripts listed in one bundle file and save a bundle-grade JSON."""

    bundle_path = Path(bundle_file_path).resolve()
    stems = _parse_bundle_file(bundle_path)
    transcripts = _load_transcripts(stems)
    conversation_text, total_turns = _format_bundle_conversation(transcripts)

    if provider == "gpt":
        model_name = os.environ.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
        api_key = _require_openai_api_key()
        reasoning = os.environ.get("JUDGE_OPENAI_REASONING_EFFORT", DEFAULT_REASONING).strip().lower() or DEFAULT_REASONING
    else:
        model_name = os.environ.get("ANTHROPIC_MODEL", DEFAULT_CLAUDE_MODEL)
        api_key = _require_anthropic_api_key()
        reasoning = "off"

    invoke_model = _create_model_invoke(provider, model_name, api_key, reasoning)
    graph = _create_judge_graph(invoke_model=invoke_model)
    result = graph.invoke(
        {
            "attempts": 0,
            "system_prompt": load_judge_prompt(prompt_name=prompt_name, rubric_name=rubric_name),
            "conversation_text": conversation_text,
            "num_turns": total_turns,
        }
    )
    grade_json = result.get("grade_json")
    if grade_json is None:
        raise JudgeError(f"Bundle judge failed: {result.get('last_error')}")

    payload = dict(grade_json)
    payload["model"] = {"provider": "openai" if provider == "gpt" else "anthropic", "model": model_name}
    payload["judge_llm_calls"] = int(result.get("attempts", 0))
    if _env_truthy("JUDGE_INCLUDE_TIMESTAMP"):
        payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    payload = _order_grade_payload(payload)

    out_doc: dict[str, Any] = {
        "bundle_file": bundle_path.name,
        "provider": provider,
        "prompt_name": prompt_name,
        "rubric_name": rubric_name,
        "transcripts": stems,
        "grade": payload,
    }
    if output_path:
        out = Path(output_path).resolve()
    else:
        out = bundle_path.with_suffix(".json")
    out.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return JudgeResult(total_score=int(payload["total_score"]), max_score=int(payload["max_score"]), output_path=out)


def judge_transcript_bundle_gpt(
    bundle_file_path: str, *, prompt_name: str = "judge_05", rubric_name: str = "rubric_05", output_path: str | None = None
) -> JudgeResult:
    """GPT-specific convenience wrapper for bundle judging."""

    return judge_transcript_bundle(
        bundle_file_path,
        provider="gpt",
        prompt_name=prompt_name,
        rubric_name=rubric_name,
        output_path=output_path,
    )


def judge_transcript_bundle_claude(
    bundle_file_path: str, *, prompt_name: str = "judge_05", rubric_name: str = "rubric_05", output_path: str | None = None
) -> JudgeResult:
    """Claude-specific convenience wrapper for bundle judging."""

    return judge_transcript_bundle(
        bundle_file_path,
        provider="claude",
        prompt_name=prompt_name,
        rubric_name=rubric_name,
        output_path=output_path,
    )


__all__ = [
    "JudgeError",
    "JudgeResult",
    "judge_transcript_bundle",
    "judge_transcript_bundle_gpt",
    "judge_transcript_bundle_claude",
]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Judge one transcript bundle with GPT or Claude.")
    parser.add_argument("bundle_file_path", help="Path to bundle .txt file")
    parser.add_argument("--provider", choices=["gpt", "claude"], default="gpt")
    parser.add_argument("--prompt", default="judge_05")
    parser.add_argument("--rubric", default="rubric_05")
    args = parser.parse_args()
    result = judge_transcript_bundle(
        args.bundle_file_path,
        provider=args.provider,  # type: ignore[arg-type]
        prompt_name=args.prompt,
        rubric_name=args.rubric,
    )
    print(f"Bundle grade: {result.total_score}/{result.max_score}")
    print(f"Output: {result.output_path}")


