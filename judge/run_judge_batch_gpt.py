"""GPT-based batch judge for humanities tutor transcripts.

Combines multiple transcripts from a batch file into a single prompt,
grades them holistically, and writes the result to disk.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from judge.run_judge_gpt import (
    JudgeError,
    _coerce_int,
    _create_judge_graph,
    _env_truthy,
    _format_conversation_for_judge,
    _order_grade_payload,
    _require_openai_api_key,
    _sanitize_text,
    load_judge_prompt,
)

TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"

_DEFAULT_OPENAI_MODEL = "gpt-5.4"

# ---------------------------------------------------------------------------
# Structured JSONL debug logging
# ---------------------------------------------------------------------------
_LOG_PATH = _REPO_ROOT / "logs" / "judge_batch_gpt_debug.jsonl"


class _JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", ""),
            "batch_name": getattr(record, "batch_name", ""),
        }
        for key, value in record.__dict__.items():
            if key.startswith("_log_"):
                field_name = key[5:]
                if isinstance(value, str) and len(value) > 50_000:
                    value = value[:50_000]
                    payload[field_name + "_truncated"] = True
                payload[field_name] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def _setup_debug_logger() -> logging.Logger:
    logger = logging.getLogger("judge_batch_gpt_debug")
    if logger.handlers:
        return logger
    logger.setLevel(logging.DEBUG)
    _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(_LOG_PATH, mode="a", encoding="utf-8")
    handler.setFormatter(_JsonLogFormatter())
    logger.addHandler(handler)
    logger.propagate = False
    return logger


_debug_log = _setup_debug_logger()


def _log_event(event: str, batch_name: str = "", level: int = logging.INFO, **fields: Any) -> None:
    extra = {"event": event, "batch_name": batch_name}
    for key, value in fields.items():
        extra[f"_log_{key}"] = value
    _debug_log.log(level, "", extra=extra)


def _sha256_short(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

@dataclass(slots=True)
class JudgeResult:
    total_score: int
    max_score: int
    output_path: Path


# ---------------------------------------------------------------------------
# Batch file parsing
# ---------------------------------------------------------------------------

def _parse_batch_file(batch_file_path: Path) -> list[str]:
    """Read a batch file and return the list of transcript relative stems."""
    if not batch_file_path.exists():
        raise JudgeError(f"Batch file not found: {batch_file_path}")
    lines = batch_file_path.read_text(encoding="utf-8").strip().splitlines()
    stems: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        stems.append(stripped.replace("\\", "/"))
    if not stems:
        raise JudgeError(f"Batch file is empty (no transcript paths): {batch_file_path}")
    return stems


def _load_transcripts(stems: list[str]) -> list[tuple[str, dict[str, Any]]]:
    """Load transcript JSONs for each stem, returning (stem, data) pairs."""
    results: list[tuple[str, dict[str, Any]]] = []
    for stem in stems:
        path = (TRANSCRIPTS_DIR / f"{stem}.json").resolve()
        if not path.exists():
            raise JudgeError(f"Transcript not found: {path} (stem: {stem})")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise JudgeError(f"Transcript is not valid JSON: {path}: {e}") from e
        if not isinstance(data, dict):
            raise JudgeError(f"Transcript JSON must be an object: {path}")
        exchanges = data.get("exchanges")
        if not isinstance(exchanges, list) or not exchanges:
            raise JudgeError(f"Transcript must contain a non-empty 'exchanges' array: {path}")
        results.append((stem, data))
    return results


# ---------------------------------------------------------------------------
# Combined conversation formatting
# ---------------------------------------------------------------------------

def _format_batch_conversation_for_judge(
    transcripts: list[tuple[str, dict[str, Any]]],
) -> tuple[str, int]:
    """Format multiple transcripts into one combined prompt.

    Returns (combined_text, total_turn_count).
    """
    parts: list[str] = []
    total_turns = 0
    count = len(transcripts)

    for idx, (stem, data) in enumerate(transcripts, start=1):
        persona = _sanitize_text(data.get("student_persona")).strip() or "unknown"
        course = _sanitize_text(data.get("course")).strip() or "unknown"
        exercise = _sanitize_text(data.get("exercise_number")).strip() or "?"
        turns = _coerce_int(data.get("turns"), default=len(data.get("exchanges", [])))
        total_turns += turns

        header_lines = [
            f"{'=' * 60}",
            f"TRANSCRIPT {idx} OF {count}",
            f"{'=' * 60}",
            f"Student Persona: {persona}",
            f"Course: {course}",
            f"Exercise: {exercise}",
            f"Turns: {turns}",
            "",
        ]
        parts.append("\n".join(header_lines))
        parts.append(_format_conversation_for_judge(data))
        parts.append("")

    return "\n\n".join(parts).strip(), total_turns


# ---------------------------------------------------------------------------
# Public API — batch transcript judging
# ---------------------------------------------------------------------------

def judge_transcript_batch(
    batch_file_path: str,
    *,
    prompt_name: str = "judge_05",
    rubric_name: str = "rubric_05",
    output_path: str | None = None,
) -> JudgeResult:
    """Grade a batch of transcripts combined into one prompt.

    Parameters
    ----------
    batch_file_path:
        Path to the batch .txt file listing transcript stems.
    prompt_name:
        Judge prompt stem from ``judge/prompts/``.
    rubric_name:
        Rubric stem from ``judge/rubrics/``.
    output_path:
        If provided, the output JSON is written here.  Otherwise a default
        path is derived from the batch file location.
    """
    batch_path = Path(batch_file_path).resolve()
    batch_name = batch_path.stem

    stems = _parse_batch_file(batch_path)
    _log_event("batch_file_parsed", batch_name,
               batch_file=str(batch_path),
               transcript_count=len(stems),
               stems=stems)

    transcripts = _load_transcripts(stems)
    _log_event("transcripts_loaded", batch_name,
               count=len(transcripts),
               personas=[_sanitize_text(d.get("student_persona")) for _, d in transcripts],
               courses=[_sanitize_text(d.get("course")) for _, d in transcripts])

    normalized_rubric = rubric_name.strip().lower()
    model_name = os.environ.get("OPENAI_MODEL", _DEFAULT_OPENAI_MODEL)
    graph = _create_judge_graph(
        model_name=model_name,
        api_key=_require_openai_api_key(),
        enforce_sub_criterion_ids=normalized_rubric in {"rubric_04", "rubric_05", "rubric_06"},
        rubric_name=normalized_rubric,
    )
    system_prompt = load_judge_prompt(prompt_name=prompt_name, rubric_name=rubric_name)
    conversation_text, total_turns = _format_batch_conversation_for_judge(transcripts)

    _log_event("batch_conversation_formatted", batch_name,
               conversation_text_length=len(conversation_text),
               conversation_text_hash=_sha256_short(conversation_text),
               total_turns=total_turns)

    result = graph.invoke(
        {
            "attempts": 0,
            "system_prompt": system_prompt,
            "conversation_text": conversation_text,
            "num_turns": total_turns,
            "transcript_name": f"batch:{batch_name}",
        }
    )
    grade_json = result.get("grade_json")
    if grade_json is None:
        raise JudgeError(
            f"Batch judge failed to produce valid grade JSON for {batch_name}. "
            f"Last error: {result.get('last_error')}"
        )

    grade_payload = dict(grade_json)
    grade_payload["model"] = {"provider": "openai", "model": model_name}
    grade_payload["judge_llm_calls"] = int(result.get("attempts", 0))
    if _env_truthy("JUDGE_INCLUDE_TIMESTAMP"):
        grade_payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    grade_payload = _order_grade_payload(grade_payload)

    out_doc: dict[str, Any] = {
        "batch_file": batch_path.name,
        "transcript_count": len(transcripts),
        "transcript_sources": stems,
        "transcripts": [data for _, data in transcripts],
        "grade": grade_payload,
    }

    if output_path is not None:
        out_path = Path(output_path).resolve()
    else:
        out_path = batch_path.with_suffix(".json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    _log_event("batch_judge_complete", batch_name,
               total_score=int(grade_payload["total_score"]),
               max_score=int(grade_payload["max_score"]),
               judge_llm_calls=int(grade_payload.get("judge_llm_calls", 0)),
               output_path=str(out_path))

    return JudgeResult(
        total_score=int(grade_payload["total_score"]),
        max_score=int(grade_payload["max_score"]),
        output_path=out_path,
    )
