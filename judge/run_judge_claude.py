"""
Re-judge existing transcripts with Claude and write to *_claude folders.

Usage (from repo root):
    python -m judge.run_judge_claude
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_anthropic import ChatAnthropic

from judge.run_judge import (
    JudgeError,
    _format_conversation_for_judge,
    _judge_repair_prompt,
    _order_grade_payload,
    _parse_json_from_model_output,
    _sanitize_grade_payload,
    _validate_grade_payload,
    load_judge_prompt,
)


_REPO_ROOT = Path(__file__).resolve().parent.parent
_TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"
_SOURCE_DIRS: tuple[str, ...] = ("chaotic", "chitchat", "clueless")
_TARGET_SUFFIX = "_claude"

# Load repo-level .env once so ANTHROPIC_API_KEY is available.
load_dotenv(_REPO_ROOT / ".env")


def _require_anthropic_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY environment variable is required but not set.")
    return key


def _ensure_empty_target_dirs() -> dict[str, Path]:
    target_dirs: dict[str, Path] = {}
    for source_name in _SOURCE_DIRS:
        target_name = f"{source_name}{_TARGET_SUFFIX}"
        target_dir = _TRANSCRIPTS_DIR / target_name
        target_dir.mkdir(parents=True, exist_ok=True)
        for path in target_dir.glob("*.json"):
            path.unlink()
        target_dirs[source_name] = target_dir
    return target_dirs


def _judge_with_claude(
    *,
    system_prompt: str,
    conversation_text: str,
    num_turns: int,
    model_name: str,
    api_key: str,
) -> tuple[dict[str, Any], int]:
    model = ChatAnthropic(model=model_name, temperature=0, api_key=api_key)
    attempts = 0
    last_output = ""
    last_error: str | None = None

    while attempts < 2:
        messages = [SystemMessage(content=system_prompt)]
        if last_error and last_output:
            messages.append(
                HumanMessage(
                    content=_judge_repair_prompt(last_error)
                    + "\n\nPrevious JSON (to repair):\n"
                    + last_output
                )
            )
        messages.append(HumanMessage(content=conversation_text))

        resp = model.invoke(messages)
        last_output = resp.content if isinstance(resp.content, str) else str(resp.content)
        attempts += 1

        try:
            parsed = _parse_json_from_model_output(last_output)
            parsed = _sanitize_grade_payload(parsed)
            validated = _validate_grade_payload(parsed, num_turns=num_turns)
            return validated, attempts
        except JudgeError as e:
            last_error = str(e)

    raise JudgeError(f"Claude judge failed after {attempts} attempts. Last error: {last_error}")


def _process_transcript_file(
    *,
    src_path: Path,
    dst_path: Path,
    system_prompt: str,
    model_name: str,
    api_key: str,
) -> None:
    transcript = json.loads(src_path.read_text(encoding="utf-8"))
    if not isinstance(transcript, dict):
        raise JudgeError(f"Transcript must be an object: {src_path}")

    exchanges = transcript.get("exchanges")
    if not isinstance(exchanges, list) or not exchanges:
        raise JudgeError(f"Transcript must contain non-empty 'exchanges': {src_path}")

    out_payload = dict(transcript)
    out_payload.pop("grade", None)

    conversation_text = _format_conversation_for_judge(out_payload)
    grade_payload, attempts = _judge_with_claude(
        system_prompt=system_prompt,
        conversation_text=conversation_text,
        num_turns=len(exchanges),
        model_name=model_name,
        api_key=api_key,
    )
    grade_payload = dict(grade_payload)
    grade_payload["model"] = {"provider": "anthropic", "model": model_name, "temperature": 0}
    grade_payload["judge_llm_calls"] = attempts
    grade_payload = _order_grade_payload(grade_payload)
    out_payload["grade"] = grade_payload

    dst_path.write_text(json.dumps(out_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-judge transcripts with Claude.")
    parser.add_argument("--model", default="claude-3-7-sonnet", help="Claude model name.")
    parser.add_argument("--prompt", default="judge_03", help="Judge prompt stem.")
    parser.add_argument("--rubric", default="rubric_03", help="Judge rubric stem.")
    args = parser.parse_args()

    api_key = _require_anthropic_api_key()
    system_prompt = load_judge_prompt(prompt_name=args.prompt, rubric_name=args.rubric)
    target_dirs = _ensure_empty_target_dirs()

    total = 0
    for source_name in _SOURCE_DIRS:
        src_dir = _TRANSCRIPTS_DIR / source_name
        dst_dir = target_dirs[source_name]
        if not src_dir.exists():
            print(f"[Skip] Missing source folder: {src_dir.relative_to(_REPO_ROOT)}")
            continue

        for src_path in sorted(src_dir.glob("*.json")):
            dst_path = dst_dir / src_path.name
            _process_transcript_file(
                src_path=src_path,
                dst_path=dst_path,
                system_prompt=system_prompt,
                model_name=args.model,
                api_key=api_key,
            )
            total += 1
            print(
                f"[OK] {src_path.relative_to(_REPO_ROOT)} -> "
                f"{dst_path.relative_to(_REPO_ROOT)}"
            )

    print(f"[Done] Claude-judged transcripts written: {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
