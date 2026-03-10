"""
LLM-based judge for humanities tutor transcripts.

Scores a conversation transcript against a rubric using LangGraph + OpenAI.
Called by the UI; not intended to run standalone.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from typing_extensions import NotRequired, TypedDict

from utils.parsing import extract_json_object

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_JUDGE_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _JUDGE_ROOT.parent
PROMPTS_DIR = _JUDGE_ROOT / "prompts"
TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"

# Load repo-level .env once so OPENAI_API_KEY is available across entrypoints.
load_dotenv(_REPO_ROOT / ".env")

# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------

def _require_openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY (or OPENAI_KEY) environment variable is required but not set."
        )
    return key


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"})


# ---------------------------------------------------------------------------
# Rubric constants
# ---------------------------------------------------------------------------

class JudgeError(RuntimeError):
    pass


_CRITERIA_MAX: dict[str, float] = {
    "1.1": 5, "1.2": 3, "1.3": 3,
    "2.1": 5, "2.2": 3, "2.3": 3,
    "3.1": 5, "3.2": 3, "3.3": 3,
}

_CRITERIA_NAME: dict[str, str] = {
    "1.1": "Socratic method and guided discovery",
    "1.2": "Scaffolding and progression",
    "1.3": "Meta-learning and methodology feedback",
    "2.1": "Redundancy and spiraling",
    "2.2": "Assignment anchoring",
    "2.3": "Focus and progression",
    "3.1": "Bite-sized and clear responses",
    "3.2": "Appropriate tone and support",
    "3.3": "Formatting and medium",
}

_SECTION_KEYS: tuple[str, ...] = (
    "1_pedagogy",
    "2_dialogue_quality",
    "3_communication_quality",
)

_SECTION_CRITERIA: dict[str, tuple[str, ...]] = {
    "1_pedagogy": ("1.1", "1.2", "1.3"),
    "2_dialogue_quality": ("2.1", "2.2", "2.3"),
    "3_communication_quality": ("3.1", "3.2", "3.3"),
}

_SECTION_BONUS_ID: dict[str, str] = {
    "1_pedagogy": "1.4",
    "2_dialogue_quality": "2.4",
    "3_communication_quality": "3.4",
}

_MAX_BASE_SCORE = float(sum(_CRITERIA_MAX.values()))  # 33
_MAX_BONUS_PER_SECTION = 4.0
_MAX_BONUS_SCORE = float(len(_SECTION_KEYS) * _MAX_BONUS_PER_SECTION)  # 12
_MAX_TOTAL_SCORE = _MAX_BASE_SCORE + _MAX_BONUS_SCORE  # 45


# ---------------------------------------------------------------------------
# JSON parsing & validation helpers
# ---------------------------------------------------------------------------

def _parse_json_from_model_output(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
        raise JudgeError("Model output JSON was not an object.")
    except json.JSONDecodeError:
        pass

    obj = extract_json_object(raw)
    if obj is None:
        raise JudgeError("Could not find a JSON object in model output.")
    try:
        data = json.loads(obj)
    except json.JSONDecodeError as e:
        raise JudgeError(f"Model output contained invalid JSON: {e}") from e
    if not isinstance(data, dict):
        raise JudgeError("Model output JSON was not an object.")
    return data


def _as_number(x: Any, *, path: str) -> float:
    if isinstance(x, (int, float)) and not isinstance(x, bool):
        return float(x)
    raise JudgeError(f"Expected number at {path}, got {type(x).__name__}.")


def _as_str(x: Any, *, path: str) -> str:
    if isinstance(x, str):
        return x
    raise JudgeError(f"Expected string at {path}, got {type(x).__name__}.")


def _as_dict(x: Any, *, path: str) -> dict[str, Any]:
    if isinstance(x, dict):
        return x
    raise JudgeError(f"Expected object at {path}, got {type(x).__name__}.")


def _as_list(x: Any, *, path: str) -> list[Any]:
    if isinstance(x, list):
        return x
    raise JudgeError(f"Expected array at {path}, got {type(x).__name__}.")


def _close_enough(a: float, b: float, *, eps: float = 1e-6) -> bool:
    return math.isfinite(a) and math.isfinite(b) and abs(a - b) <= eps


def _coerce_number(x: Any) -> float | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        v = float(x)
        return v if math.isfinite(v) else None
    return None


def _clamp(v: float, lo: float, hi: float) -> float:
    return min(max(v, lo), hi)


# ---------------------------------------------------------------------------
# Sanitization & validation
# ---------------------------------------------------------------------------

def _sanitize_grade_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Best-effort fix-up for common LLM numeric mistakes.

    Recomputes criterion scores from deductions, recomputes section and global
    totals, and overwrites declared maxima to constants.
    """
    sections_any = payload.get("sections")
    if not isinstance(sections_any, dict):
        return payload

    computed_total_base = 0.0
    computed_total_bonus = 0.0

    for section_key in _SECTION_KEYS:
        sec_any = sections_any.get(section_key)
        if not isinstance(sec_any, dict):
            continue

        base_any = sec_any.get("base")
        bonus_any = sec_any.get("bonus")
        crit_any = sec_any.get("criteria")
        if not isinstance(base_any, dict) or not isinstance(bonus_any, dict) or not isinstance(crit_any, dict):
            continue

        expected_base_max = float(sum(_CRITERIA_MAX[c] for c in _SECTION_CRITERIA[section_key]))
        base_any["max"] = expected_base_max

        expected_bonus_id = _SECTION_BONUS_ID[section_key]
        bonus_any["id"] = expected_bonus_id
        bonus_any["max"] = _MAX_BONUS_PER_SECTION
        bonus_score = _coerce_number(bonus_any.get("score"))
        bonus_any["score"] = _clamp(bonus_score if bonus_score is not None else 0.0, 0.0, _MAX_BONUS_PER_SECTION)

        computed_section_base = 0.0
        for crit_id in _SECTION_CRITERIA[section_key]:
            c_any = crit_any.get(crit_id)
            if not isinstance(c_any, dict):
                continue
            c_any["name"] = _CRITERIA_NAME[crit_id]
            crit_max = float(_CRITERIA_MAX[crit_id])
            c_any["max"] = crit_max

            deductions_any = c_any.get("deductions")
            deductions_list = deductions_any if isinstance(deductions_any, list) else []
            c_any["deductions"] = deductions_list

            deduction_total = 0.0
            for d_any in deductions_list:
                if not isinstance(d_any, dict):
                    continue
                pts = _coerce_number(d_any.get("points"))
                if pts is None or pts <= 0:
                    continue
                deduction_total += float(pts)

            c_any["score"] = _clamp(crit_max - deduction_total, 0.0, crit_max)
            computed_section_base += float(c_any["score"])

        base_any["score"] = computed_section_base
        computed_total_base += float(base_any["score"])
        computed_total_bonus += float(bonus_any["score"])

    payload["max_base_score"] = _MAX_BASE_SCORE
    payload["max_bonus"] = _MAX_BONUS_SCORE
    payload["max_score"] = _MAX_TOTAL_SCORE
    payload["total_base_score"] = computed_total_base
    payload["total_bonus"] = computed_total_bonus
    payload["total_score"] = computed_total_base + computed_total_bonus
    payload["sections"] = sections_any
    return payload


def _order_grade_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Rebuild grade payload with deterministic key ordering.

    Top-level order:
      justifications, totals/maxima, sections, remaining keys.
    Per-section order:
      criteria (with deductions-first criterion shape), then base/bonus totals.
    """
    ordered: dict[str, Any] = {}
    ordered["justifications"] = payload.get("justifications", [])
    ordered["total_score"] = payload.get("total_score")
    ordered["max_score"] = payload.get("max_score")
    ordered["total_base_score"] = payload.get("total_base_score")
    ordered["max_base_score"] = payload.get("max_base_score")
    ordered["total_bonus"] = payload.get("total_bonus")
    ordered["max_bonus"] = payload.get("max_bonus")

    sections_any = payload.get("sections")
    if isinstance(sections_any, dict):
        ordered_sections: dict[str, Any] = {}
        for section_key in _SECTION_KEYS:
            sec_any = sections_any.get(section_key)
            if not isinstance(sec_any, dict):
                continue

            section_out: dict[str, Any] = {}
            crit_any = sec_any.get("criteria")
            if isinstance(crit_any, dict):
                criteria_out: dict[str, Any] = {}
                for crit_id in _SECTION_CRITERIA[section_key]:
                    c_any = crit_any.get(crit_id)
                    if not isinstance(c_any, dict):
                        continue

                    c_out: dict[str, Any] = {}
                    c_out["deductions"] = c_any.get("deductions", [])
                    c_out["score"] = c_any.get("score")
                    c_out["max"] = c_any.get("max")
                    c_out["name"] = c_any.get("name")
                    for k, v in c_any.items():
                        if k not in c_out:
                            c_out[k] = v
                    criteria_out[crit_id] = c_out
                section_out["criteria"] = criteria_out

            section_out["base"] = sec_any.get("base")
            section_out["bonus"] = sec_any.get("bonus")
            for k, v in sec_any.items():
                if k not in section_out:
                    section_out[k] = v
            ordered_sections[section_key] = section_out
        ordered["sections"] = ordered_sections
    else:
        ordered["sections"] = sections_any

    for k, v in payload.items():
        if k not in ordered:
            ordered[k] = v
    return ordered


def _validate_grade_payload(payload: dict[str, Any], *, num_turns: int) -> dict[str, Any]:
    total_score = _as_number(payload.get("total_score"), path="total_score")
    max_score = _as_number(payload.get("max_score"), path="max_score")
    total_base_score = _as_number(payload.get("total_base_score"), path="total_base_score")
    max_base_score = _as_number(payload.get("max_base_score"), path="max_base_score")
    total_bonus = _as_number(payload.get("total_bonus"), path="total_bonus")
    max_bonus = _as_number(payload.get("max_bonus"), path="max_bonus")
    sections = _as_dict(payload.get("sections"), path="sections")

    if not _close_enough(max_base_score, _MAX_BASE_SCORE):
        raise JudgeError(f"max_base_score must be {_MAX_BASE_SCORE}, got {max_base_score}.")
    if not _close_enough(max_bonus, _MAX_BONUS_SCORE):
        raise JudgeError(f"max_bonus must be {_MAX_BONUS_SCORE}, got {max_bonus}.")
    if not _close_enough(max_score, _MAX_TOTAL_SCORE):
        raise JudgeError(f"max_score must be {_MAX_TOTAL_SCORE}, got {max_score}.")
    if total_base_score < 0 or total_base_score > max_base_score:
        raise JudgeError("total_base_score out of range.")
    if total_bonus < 0 or total_bonus > max_bonus:
        raise JudgeError("total_bonus out of range.")
    if total_score < 0 or total_score > max_score:
        raise JudgeError("total_score out of range.")
    if not _close_enough(total_score, total_base_score + total_bonus):
        raise JudgeError("total_score must equal total_base_score + total_bonus.")

    for expected_section in _SECTION_KEYS:
        if expected_section not in sections:
            raise JudgeError(f"Missing sections.{expected_section}.")

    computed_total_base = 0.0
    computed_total_bonus = 0.0

    for section_key in _SECTION_KEYS:
        section = _as_dict(sections.get(section_key), path=f"sections.{section_key}")
        base = _as_dict(section.get("base"), path=f"sections.{section_key}.base")
        bonus = _as_dict(section.get("bonus"), path=f"sections.{section_key}.bonus")
        criteria = _as_dict(section.get("criteria"), path=f"sections.{section_key}.criteria")

        base_score = _as_number(base.get("score"), path=f"sections.{section_key}.base.score")
        base_max = _as_number(base.get("max"), path=f"sections.{section_key}.base.max")
        bonus_score = _as_number(bonus.get("score"), path=f"sections.{section_key}.bonus.score")
        bonus_max = _as_number(bonus.get("max"), path=f"sections.{section_key}.bonus.max")
        bonus_id = _as_str(bonus.get("id"), path=f"sections.{section_key}.bonus.id")
        expected_bonus_id = _SECTION_BONUS_ID.get(section_key)
        if bonus_id != expected_bonus_id:
            raise JudgeError(
                f"sections.{section_key}.bonus.id must be {expected_bonus_id!r}, got {bonus_id!r}."
            )

        expected_base_max = float(sum(_CRITERIA_MAX[c] for c in _SECTION_CRITERIA[section_key]))
        if not _close_enough(base_max, expected_base_max):
            raise JudgeError(
                f"sections.{section_key}.base.max must be {expected_base_max}, got {base_max}."
            )
        if not _close_enough(bonus_max, _MAX_BONUS_PER_SECTION):
            raise JudgeError(
                f"sections.{section_key}.bonus.max must be {_MAX_BONUS_PER_SECTION}, got {bonus_max}."
            )
        if base_score < 0 or base_score > base_max:
            raise JudgeError(f"sections.{section_key}.base.score out of range.")
        if bonus_score < 0 or bonus_score > bonus_max:
            raise JudgeError(f"sections.{section_key}.bonus.score out of range.")

        computed_section_base = 0.0
        for crit_id in _SECTION_CRITERIA[section_key]:
            crit = _as_dict(criteria.get(crit_id), path=f"sections.{section_key}.criteria.{crit_id}")
            crit_score = _as_number(crit.get("score"), path=f"sections.{section_key}.criteria.{crit_id}.score")
            crit_max = _as_number(crit.get("max"), path=f"sections.{section_key}.criteria.{crit_id}.max")
            _as_str(crit.get("name"), path=f"sections.{section_key}.criteria.{crit_id}.name")

            expected_crit_max = float(_CRITERIA_MAX[crit_id])
            if not _close_enough(crit_max, expected_crit_max):
                raise JudgeError(
                    f"sections.{section_key}.criteria.{crit_id}.max must be {expected_crit_max}, got {crit_max}."
                )
            if crit_score < 0 or crit_score > crit_max:
                raise JudgeError(f"sections.{section_key}.criteria.{crit_id}.score out of range.")

            deductions = _as_list(
                crit.get("deductions", []), path=f"sections.{section_key}.criteria.{crit_id}.deductions"
            )
            deduction_total = 0.0
            for i, d in enumerate(deductions):
                dd = _as_dict(d, path=f"sections.{section_key}.criteria.{crit_id}.deductions[{i}]")
                pts = _as_number(dd.get("points"), path=f"...deductions[{i}].points")
                if pts <= 0:
                    raise JudgeError("Deduction points must be > 0.")
                deduction_total += pts
                _as_str(dd.get("reason"), path=f"...deductions[{i}].reason")
                ev = dd.get("evidence_turns")
                if ev is not None:
                    turns = _as_list(ev, path=f"...deductions[{i}].evidence_turns")
                    for t in turns:
                        n = _as_number(t, path=f"...deductions[{i}].evidence_turns[]")
                        if not float(n).is_integer():
                            raise JudgeError("Evidence turn numbers must be integers.")
                        ti = int(n)
                        if ti < 1 or ti > num_turns:
                            raise JudgeError("Evidence turn number out of range.")

            expected_crit_score = _clamp(float(crit_max) - float(deduction_total), 0.0, float(crit_max))
            if not _close_enough(float(crit_score), expected_crit_score):
                raise JudgeError(
                    f"sections.{section_key}.criteria.{crit_id}.score must equal max - sum(deductions.points)."
                )
            computed_section_base += crit_score

        if not _close_enough(base_score, computed_section_base):
            raise JudgeError(f"sections.{section_key}.base.score must equal sum of criteria scores.")

        computed_total_base += base_score
        computed_total_bonus += bonus_score

    if not _close_enough(total_base_score, computed_total_base):
        raise JudgeError("total_base_score must equal sum of section base scores.")
    if not _close_enough(total_bonus, computed_total_bonus):
        raise JudgeError("total_bonus must equal sum of section bonus scores.")

    return payload


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

def _build_expected_schema() -> dict[str, Any]:
    """Build the example JSON schema shown to the judge in the prompt."""
    sections: dict[str, Any] = {}
    for section_key in _SECTION_KEYS:
        criteria: dict[str, Any] = {}
        for crit_id in _SECTION_CRITERIA[section_key]:
            criteria[crit_id] = {
                "deductions": [
                    {"points": 1, "reason": "Short reason", "evidence_turns": [1]},
                ],
                "score": 0,
                "max": _CRITERIA_MAX[crit_id],
                "name": _CRITERIA_NAME[crit_id],
            }
        sections[section_key] = {
            "criteria": criteria,
            "base": {"score": 0, "max": float(sum(_CRITERIA_MAX[c] for c in _SECTION_CRITERIA[section_key]))},
            "bonus": {"id": _SECTION_BONUS_ID[section_key], "score": 0, "max": _MAX_BONUS_PER_SECTION},
        }
    return {
        "justifications": ["Brief overall rationale."],
        "total_score": 0,
        "max_score": _MAX_TOTAL_SCORE,
        "total_base_score": 0,
        "max_base_score": _MAX_BASE_SCORE,
        "total_bonus": 0,
        "max_bonus": _MAX_BONUS_SCORE,
        "sections": sections,
    }


def load_judge_prompt(
    prompt_name: str = "judge_01",
    rubric_name: str = "rubric_01",
) -> str:
    """
    Load the judge system prompt from ``judge/prompts/<prompt_name>.txt``,
    injecting the rubric and expected JSON schema.
    """
    prompt_path = PROMPTS_DIR / f"{prompt_name}.txt"
    if not prompt_path.exists():
        raise FileNotFoundError(f"Judge prompt not found: {prompt_path}")

    rubric_path = _JUDGE_ROOT / "rubrics" / f"{rubric_name}.md"
    if not rubric_path.exists():
        raise FileNotFoundError(f"Rubric not found: {rubric_path}")

    template = prompt_path.read_text(encoding="utf-8")
    rubric_text = rubric_path.read_text(encoding="utf-8").strip()
    schema_text = json.dumps(_build_expected_schema(), indent=2)

    return template.format(rubric=rubric_text, schema=schema_text).strip()


def _judge_repair_prompt(error: str) -> str:
    return (
        "Your previous JSON did not validate against the required schema / consistency rules.\n"
        f"Validation error: {error}\n\n"
        "Return a corrected JSON ONLY that fixes the error while keeping your original grading intent.\n"
        "Do NOT add any extra keys. Ensure all totals and maxima are correct and consistent.\n"
    )


# ---------------------------------------------------------------------------
# Conversation formatting
# ---------------------------------------------------------------------------

def _format_conversation_for_judge(transcript: dict[str, Any]) -> str:
    exercise = transcript.get("exercise", "")
    exchanges = transcript.get("exchanges", [])
    lines: list[str] = []
    lines.append("Exercise / assignment context:")
    lines.append(str(exercise).strip())
    lines.append("")
    lines.append("Conversation transcript (student+tutor exchanges):")
    for ex in exchanges:
        turn = ex.get("turn")
        student = ex.get("student", "")
        tutor = ex.get("tutor", "")
        lines.append(f"Turn {turn} — Student: {student}")
        lines.append(f"Turn {turn} — Tutor: {tutor}")
        lines.append("")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# LangGraph
# ---------------------------------------------------------------------------

class _JudgeState(TypedDict):
    attempts: int
    system_prompt: str
    conversation_text: str
    num_turns: int
    last_output: NotRequired[str]
    last_error: NotRequired[str]
    grade_json: NotRequired[dict[str, Any]]


def _create_judge_graph(*, model_name: str, api_key: str):
    model = ChatOpenAI(model=model_name, temperature=0, api_key=api_key)

    def judge_node(state: _JudgeState) -> dict[str, Any]:
        messages = [SystemMessage(content=state["system_prompt"])]
        if state.get("last_error") and state.get("last_output"):
            messages.append(
                HumanMessage(
                    content=_judge_repair_prompt(state["last_error"])
                    + "\n\nPrevious JSON (to repair):\n"
                    + state["last_output"]
                )
            )
        messages.append(HumanMessage(content=state["conversation_text"]))
        resp = model.invoke(messages)
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        return {"last_output": content, "attempts": int(state.get("attempts", 0)) + 1}

    def validate_node(state: _JudgeState) -> dict[str, Any]:
        out = state.get("last_output", "")
        try:
            parsed = _parse_json_from_model_output(out)
            parsed = _sanitize_grade_payload(parsed)
            validated = _validate_grade_payload(parsed, num_turns=int(state["num_turns"]))
            ordered = _order_grade_payload(validated)
            return {"grade_json": ordered, "last_error": None}
        except JudgeError as e:
            return {"last_error": str(e), "grade_json": None}

    graph = StateGraph(_JudgeState)
    graph.add_node("judge", judge_node)
    graph.add_node("validate", validate_node)
    graph.add_edge(START, "judge")
    graph.add_edge("judge", "validate")

    def _route(state: _JudgeState) -> str:
        if state.get("grade_json") is not None:
            return END
        if int(state.get("attempts", 0)) >= 2:
            return END
        return "judge"

    graph.add_conditional_edges("validate", _route, {"judge": "judge", END: END})
    return graph.compile()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class JudgeResult:
    total_score: float
    max_score: float


def judge_transcript(
    transcript_name: str,
    *,
    prompt_name: str = "judge_01",
    rubric_name: str = "rubric_01",
) -> JudgeResult:
    """
    Score one transcript by relative path (without .json) under transcripts/.

    Examples: ``"chaotic/transcript_01"`` or ``"transcript_01"``.

    Side effect: updates the transcript JSON in-place by adding a top-level
    ``grade`` object.
    """
    name = (transcript_name or "").strip()
    if not name:
        raise JudgeError("transcript_name is required (path without .json).")

    transcript_path = TRANSCRIPTS_DIR / f"{name}.json"
    if not transcript_path.exists():
        raise JudgeError(f"Transcript not found: {transcript_path}")

    try:
        transcript = json.loads(transcript_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise JudgeError(f"Transcript is not valid JSON: {e}") from e
    if not isinstance(transcript, dict):
        raise JudgeError("Transcript JSON must be an object.")
    if "grade" in transcript:
        raise JudgeError("Transcript already contains a top-level 'grade' key; refusing to overwrite.")

    exchanges = transcript.get("exchanges")
    if not isinstance(exchanges, list) or not exchanges:
        raise JudgeError("Transcript must contain a non-empty 'exchanges' array.")

    api_key = _require_openai_api_key()
    model_name = os.environ.get("OPENAI_MODEL", "gpt-5.2")

    system_prompt = load_judge_prompt(prompt_name=prompt_name, rubric_name=rubric_name)
    conversation_text = _format_conversation_for_judge(transcript)

    graph = _create_judge_graph(model_name=model_name, api_key=api_key)
    result = graph.invoke(
        {
            "attempts": 0,
            "system_prompt": system_prompt,
            "conversation_text": conversation_text,
            "num_turns": len(exchanges),
        }
    )
    grade_json = result.get("grade_json")
    if grade_json is None:
        raise JudgeError(f"Judge failed to produce valid grade JSON. Last error: {result.get('last_error')}")

    grade_payload = dict(grade_json)
    grade_payload["model"] = {"provider": "openai", "model": model_name, "temperature": 0}
    # Keep grade artifacts deterministic by default; timestamp is opt-in.
    if _env_truthy("JUDGE_INCLUDE_TIMESTAMP"):
        grade_payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    grade_payload = _order_grade_payload(grade_payload)

    transcript["grade"] = grade_payload
    transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return JudgeResult(
        total_score=float(grade_payload["total_score"]),
        max_score=float(grade_payload["max_score"]),
    )
