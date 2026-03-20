"""GPT-based judge for humanities tutor transcripts."""

from __future__ import annotations

import ast
import json
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from typing_extensions import NotRequired, TypedDict

from utils.parsing import extract_json_object

_REPO_ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"
_PROMPTS_DIR = _REPO_ROOT / "judge" / "prompts"
_RUBRICS_DIR = _REPO_ROOT / "judge" / "rubrics"

_DEFAULT_OPENAI_MODEL = "gpt-5.2"
_ALLOWED_REASONING = {"low", "medium", "high", "off"}
_DEFAULT_REASONING = "medium"
_MAX_ATTEMPTS = 3

_SECTION_KEYS = ("pedagogy", "dialogue", "communication")
_SECTION_CRITERIA: dict[str, tuple[str, ...]] = {
    "pedagogy": ("1.1", "1.2", "1.3"),
    "dialogue": ("2.1", "2.2"),
    "communication": ("3.1", "3.2", "3.3"),
}
_SECTION_MALUS_ID = {"pedagogy": "1.4", "dialogue": "2.3", "communication": "3.4"}
_CRITERIA_MAX = {"1.1": 12, "1.2": 6, "1.3": 5, "2.1": 4, "2.2": 6, "3.1": 6, "3.2": 5, "3.3": 3}
_CRITERIA_NAME = {
    "1.1": "Socratic method, guided discovery, and direct work",
    "1.2": "Scaffolding and progression",
    "1.3": "Meta-learning and methodology feedback",
    "2.1": "Redundancy and spiraling",
    "2.2": "Assignment anchoring",
    "3.1": "Bite-sized and clear responses",
    "3.2": "Appropriate tone and support",
    "3.3": "Formatting and medium",
}
_MAX_BASE_SCORE = 47
_MAX_MALUS_SECTION = 2
_MAX_MALUS_TOTAL = 6
_MAX_TOTAL_SCORE = 47


class JudgeError(RuntimeError):
    """Raised when parsing/validation fails for judge output."""


@dataclass(frozen=True)
class JudgeResult:
    total_score: int
    max_score: int
    output_path: Path


def _env_truthy(name: str) -> bool:
    value = (os.environ.get(name) or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _require_openai_api_key() -> str:
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")
    if not key:
        raise JudgeError("OPENAI_API_KEY (or OPENAI_KEY) environment variable is required but not set.")
    return key


def _openai_reasoning_effort() -> str:
    effort = (os.environ.get("JUDGE_OPENAI_REASONING_EFFORT") or _DEFAULT_REASONING).strip().lower()
    if effort not in _ALLOWED_REASONING:
        raise JudgeError("JUDGE_OPENAI_REASONING_EFFORT must be one of: low, medium, high, off.")
    return effort


def _openai_reasoning_config() -> dict[str, Any]:
    effort = _openai_reasoning_effort()
    if effort == "off":
        return {}
    return {"effort": effort}


def _parse_python_dict_literal(text: str) -> dict[str, Any] | None:
    try:
        value = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None
    if isinstance(value, dict):
        return _to_json_compatible(value)
    return None


def _to_json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_json_compatible(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_json_compatible(v) for v in value]
    if isinstance(value, tuple):
        return [_to_json_compatible(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _parse_json_from_model_output(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        raise JudgeError("Model output was empty.")

    py_data = _parse_python_dict_literal(raw)
    if py_data is not None:
        return py_data

    obj = extract_json_object(raw)
    if obj is None:
        raise JudgeError("Could not find a JSON object in model output.")
    try:
        data = json.loads(obj)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        py_data = _parse_python_dict_literal(obj)
        if py_data is not None:
            return py_data
    raise JudgeError("Model output JSON was invalid.")


def _as_dict(x: Any, *, path: str) -> dict[str, Any]:
    if isinstance(x, dict):
        return x
    raise JudgeError(f"Expected object at {path}, got {type(x).__name__}.")


def _as_list(x: Any, *, path: str) -> list[Any]:
    if isinstance(x, list):
        return x
    raise JudgeError(f"Expected array at {path}, got {type(x).__name__}.")


def _as_int(x: Any, *, path: str) -> int:
    if isinstance(x, bool):
        raise JudgeError(f"Expected integer at {path}, got bool.")
    if isinstance(x, int):
        return x
    if isinstance(x, float) and math.isfinite(x) and x.is_integer():
        return int(x)
    raise JudgeError(f"Expected integer at {path}, got {type(x).__name__}.")


def _coerce_int(x: Any) -> int | None:
    if isinstance(x, bool):
        return None
    if isinstance(x, int):
        return x
    if isinstance(x, float) and math.isfinite(x) and x.is_integer():
        return int(x)
    return None


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(v, hi))


def _is_complete_grade_shape(payload: dict[str, Any]) -> bool:
    sections = payload.get("sections")
    if not isinstance(sections, dict):
        return False
    for section_key in _SECTION_KEYS:
        sec = sections.get(section_key)
        if not isinstance(sec, dict):
            return False
        if not isinstance(sec.get("criteria"), dict):
            return False
        if not isinstance(sec.get("base"), dict):
            return False
        if not isinstance(sec.get("malus"), dict):
            return False
        for crit in _SECTION_CRITERIA[section_key]:
            if not isinstance(sec["criteria"].get(crit), dict):
                return False
    return True


def _unwrap_grade_payload(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("sections"), dict):
        return payload
    for key in ("grade", "result", "output", "data", "response"):
        inner = payload.get(key)
        if isinstance(inner, dict) and isinstance(inner.get("sections"), dict):
            return inner
    dict_values = [v for v in payload.values() if isinstance(v, dict)]
    if len(dict_values) == 1 and isinstance(dict_values[0].get("sections"), dict):
        return dict_values[0]
    return payload


def _sanitize_grade_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = _unwrap_grade_payload(dict(payload))
    if "overview" not in out:
        out["overview"] = out.get("justifications", []) if isinstance(out.get("justifications"), list) else []

    if not _is_complete_grade_shape(out):
        return out

    sections_in = _as_dict(out["sections"], path="sections")
    sections_out: dict[str, Any] = {}
    total_base = 0
    total_malus = 0

    for section_key in _SECTION_KEYS:
        sec_in = _as_dict(sections_in.get(section_key), path=f"sections.{section_key}")
        crit_in = _as_dict(sec_in.get("criteria"), path=f"sections.{section_key}.criteria")
        crit_out: dict[str, Any] = {}
        section_base = 0

        for crit_id in _SECTION_CRITERIA[section_key]:
            c_in = _as_dict(crit_in.get(crit_id), path=f"sections.{section_key}.criteria.{crit_id}")
            deductions = c_in.get("deductions") if isinstance(c_in.get("deductions"), list) else []
            d_out: list[dict[str, Any]] = []
            total_deduction = 0
            for d in deductions:
                if not isinstance(d, dict):
                    continue
                dd: dict[str, Any] = {}
                if isinstance(d.get("evidence_turns"), list):
                    turns = [t for t in (_coerce_int(x) for x in d["evidence_turns"]) if t is not None]
                    if turns:
                        dd["evidence_turns"] = turns
                dd["sub_criterion_id"] = str(d.get("sub_criterion_id", "")).strip()
                dd["reason"] = str(d.get("reason", "")).strip()
                points = _coerce_int(d.get("points"))
                dd["points"] = points if points is not None else d.get("points")
                d_out.append(dd)
                if points is not None and points > 0:
                    total_deduction += points

            crit_max = _CRITERIA_MAX[crit_id]
            score = _clamp(crit_max - total_deduction, 0, crit_max)
            crit_out[crit_id] = {"deductions": d_out, "score": score, "max": crit_max, "name": _CRITERIA_NAME[crit_id]}
            section_base += score

        malus_in = _as_dict(sec_in.get("malus"), path=f"sections.{section_key}.malus")
        malus_raw = _coerce_int(malus_in.get("score"))
        if malus_raw is None:
            malus_score_out: Any = malus_in.get("score")
            malus_for_total = 0
        else:
            malus_score_out = _clamp(malus_raw, 0, _MAX_MALUS_SECTION)
            malus_for_total = malus_score_out

        sections_out[section_key] = {
            "criteria": crit_out,
            "base": {"score": section_base, "max": sum(_CRITERIA_MAX[c] for c in _SECTION_CRITERIA[section_key])},
            "malus": {
                "id": _SECTION_MALUS_ID[section_key],
                "explanation": str(malus_in.get("explanation", "")).strip(),
                "score": malus_score_out,
                "max": _MAX_MALUS_SECTION,
            },
        }
        total_base += section_base
        total_malus += malus_for_total

    out["sections"] = sections_out
    out["total_base_score"] = total_base
    out["max_base_score"] = _MAX_BASE_SCORE
    out["total_malus"] = total_malus
    out["max_malus"] = _MAX_MALUS_TOTAL
    out["max_score"] = _MAX_TOTAL_SCORE
    out["total_score"] = _clamp(total_base - total_malus, 0, _MAX_TOTAL_SCORE)
    return out


def _order_grade_payload(payload: dict[str, Any]) -> dict[str, Any]:
    ordered: dict[str, Any] = {}
    sections = payload.get("sections")
    if isinstance(sections, dict):
        sections_out: dict[str, Any] = {}
        for section_key in _SECTION_KEYS:
            sec = sections.get(section_key)
            if not isinstance(sec, dict):
                continue
            criteria = sec.get("criteria")
            criteria_out: dict[str, Any] = {}
            if isinstance(criteria, dict):
                for crit_id in _SECTION_CRITERIA[section_key]:
                    crit = criteria.get(crit_id)
                    if not isinstance(crit, dict):
                        continue
                    deductions: list[dict[str, Any]] = []
                    if isinstance(crit.get("deductions"), list):
                        for d in crit["deductions"]:
                            if not isinstance(d, dict):
                                continue
                            dd: dict[str, Any] = {}
                            if isinstance(d.get("evidence_turns"), list):
                                dd["evidence_turns"] = d["evidence_turns"]
                            dd["sub_criterion_id"] = d.get("sub_criterion_id", "")
                            dd["reason"] = d.get("reason", "")
                            dd["points"] = d.get("points", 0)
                            deductions.append(dd)
                    criteria_out[crit_id] = {
                        "deductions": deductions,
                        "score": crit.get("score", 0),
                        "max": crit.get("max", _CRITERIA_MAX[crit_id]),
                        "name": crit.get("name", _CRITERIA_NAME[crit_id]),
                    }
            sections_out[section_key] = {
                "criteria": criteria_out,
                "base": sec.get("base", {"score": 0, "max": 0}),
                "malus": sec.get(
                    "malus",
                    {"id": _SECTION_MALUS_ID[section_key], "explanation": "", "score": 0, "max": _MAX_MALUS_SECTION},
                ),
            }
        ordered["sections"] = sections_out

    for key in ("total_base_score", "max_base_score", "total_malus", "max_malus", "max_score", "overview", "total_score"):
        if key in payload:
            ordered[key] = payload[key]
    for key in ("model", "timestamp_utc", "judge_llm_calls"):
        if key in payload:
            ordered[key] = payload[key]
    return ordered


@lru_cache(maxsize=1)
def _rubric_04_sub_ids() -> frozenset[str]:
    rubric_path = _RUBRICS_DIR / "rubric_04.md"
    if not rubric_path.exists():
        raise JudgeError(f"Rubric file not found: {rubric_path}")
    text = rubric_path.read_text(encoding="utf-8")
    ids = set(re.findall(r"(?m)^\s*-\s*((?:[1-3]\.[1-4])\.[A-Z]\.[a-z])\b", text))
    if not ids:
        raise JudgeError("No rubric_04 sub-criterion IDs discovered.")
    return frozenset(ids)


def _validate_grade_payload(payload: dict[str, Any], *, num_turns: int, enforce_sub_criterion_ids: bool) -> dict[str, Any]:
    root = _as_dict(payload, path="$")
    sections = _as_dict(root.get("sections"), path="sections")
    valid_sub_ids = _rubric_04_sub_ids() if enforce_sub_criterion_ids else frozenset()
    total_base = 0
    total_malus = 0

    for section_key in _SECTION_KEYS:
        sec = _as_dict(sections.get(section_key), path=f"sections.{section_key}")
        criteria = _as_dict(sec.get("criteria"), path=f"sections.{section_key}.criteria")
        section_base = 0

        for crit_id in _SECTION_CRITERIA[section_key]:
            crit = _as_dict(criteria.get(crit_id), path=f"sections.{section_key}.criteria.{crit_id}")
            deductions = _as_list(crit.get("deductions"), path=f"sections.{section_key}.criteria.{crit_id}.deductions")
            deduction_total = 0

            for i, d in enumerate(deductions):
                dpath = f"sections.{section_key}.criteria.{crit_id}.deductions[{i}]"
                dd = _as_dict(d, path=dpath)
                if not str(dd.get("reason", "")).strip():
                    raise JudgeError(f"Deduction reason must be non-empty at {dpath}.reason")
                points = _as_int(dd.get("points"), path=f"{dpath}.points")
                if points <= 0:
                    raise JudgeError(f"Deduction points must be > 0 at {dpath}.points")
                if "evidence_turns" in dd:
                    turns = _as_list(dd.get("evidence_turns"), path=f"{dpath}.evidence_turns")
                    for ti, turn in enumerate(turns):
                        t = _as_int(turn, path=f"{dpath}.evidence_turns[{ti}]")
                        if t < 1 or t > num_turns:
                            raise JudgeError(
                                f"evidence_turn out of bounds at {dpath}.evidence_turns[{ti}] "
                                f"(got {t}, expected 1..{num_turns})."
                            )
                if enforce_sub_criterion_ids:
                    sid = str(dd.get("sub_criterion_id", "")).strip()
                    if not sid:
                        raise JudgeError(f"sub_criterion_id is required at {dpath}.sub_criterion_id")
                    if sid not in valid_sub_ids:
                        raise JudgeError(f"Unknown sub_criterion_id at {dpath}.sub_criterion_id: {sid}")
                deduction_total += points

            expected_score = _clamp(_CRITERIA_MAX[crit_id] - deduction_total, 0, _CRITERIA_MAX[crit_id])
            crit_score = _as_int(crit.get("score"), path=f"sections.{section_key}.criteria.{crit_id}.score")
            crit_max = _as_int(crit.get("max"), path=f"sections.{section_key}.criteria.{crit_id}.max")
            if crit_max != _CRITERIA_MAX[crit_id]:
                raise JudgeError(f"Invalid criterion max at sections.{section_key}.criteria.{crit_id}.max")
            if crit_score != expected_score:
                raise JudgeError(
                    f"Inconsistent criterion score at sections.{section_key}.criteria.{crit_id}.score "
                    f"(expected {expected_score}, got {crit_score})."
                )
            section_base += crit_score

        base = _as_dict(sec.get("base"), path=f"sections.{section_key}.base")
        if _as_int(base.get("score"), path=f"sections.{section_key}.base.score") != section_base:
            raise JudgeError(f"Inconsistent section base score at sections.{section_key}.base.score")
        section_max = sum(_CRITERIA_MAX[c] for c in _SECTION_CRITERIA[section_key])
        if _as_int(base.get("max"), path=f"sections.{section_key}.base.max") != section_max:
            raise JudgeError(f"Invalid section base max at sections.{section_key}.base.max")

        malus = _as_dict(sec.get("malus"), path=f"sections.{section_key}.malus")
        if str(malus.get("id", "")).strip() != _SECTION_MALUS_ID[section_key]:
            raise JudgeError(f"Invalid malus id at sections.{section_key}.malus.id")
        malus_score = _as_int(malus.get("score"), path=f"sections.{section_key}.malus.score")
        malus_max = _as_int(malus.get("max"), path=f"sections.{section_key}.malus.max")
        if malus_max != _MAX_MALUS_SECTION:
            raise JudgeError(f"Invalid malus max at sections.{section_key}.malus.max")
        if malus_score < 0 or malus_score > _MAX_MALUS_SECTION:
            raise JudgeError(f"malus.score out of range at sections.{section_key}.malus.score")
        if malus_score > 0 and not str(malus.get("explanation", "")).strip():
            raise JudgeError(f"malus.explanation must be non-empty when malus.score > 0 at sections.{section_key}")

        total_base += section_base
        total_malus += malus_score

    total_base_score = _as_int(root.get("total_base_score"), path="total_base_score")
    max_base_score = _as_int(root.get("max_base_score"), path="max_base_score")
    total_malus_score = _as_int(root.get("total_malus"), path="total_malus")
    max_malus_score = _as_int(root.get("max_malus"), path="max_malus")
    max_score = _as_int(root.get("max_score"), path="max_score")
    total_score = _as_int(root.get("total_score"), path="total_score")

    if total_base_score != total_base:
        raise JudgeError(f"Inconsistent total_base_score (expected {total_base}, got {total_base_score}).")
    if max_base_score != _MAX_BASE_SCORE:
        raise JudgeError(f"Invalid max_base_score (expected {_MAX_BASE_SCORE}, got {max_base_score}).")
    if total_malus_score != total_malus:
        raise JudgeError(f"Inconsistent total_malus (expected {total_malus}, got {total_malus_score}).")
    if max_malus_score != _MAX_MALUS_TOTAL:
        raise JudgeError(f"Invalid max_malus (expected {_MAX_MALUS_TOTAL}, got {max_malus_score}).")
    if max_score != _MAX_TOTAL_SCORE:
        raise JudgeError(f"Invalid max_score (expected {_MAX_TOTAL_SCORE}, got {max_score}).")

    expected_total = _clamp(total_base - total_malus, 0, _MAX_TOTAL_SCORE)
    if total_score != expected_total:
        raise JudgeError(f"Inconsistent total_score (expected {expected_total}, got {total_score}).")

    overview = _as_list(root.get("overview"), path="overview")
    if total_score == _MAX_TOTAL_SCORE and not any(isinstance(x, str) and x.strip() for x in overview):
        raise JudgeError("Perfect score requires at least one non-empty overview rationale.")
    return root


def _build_expected_schema(*, rubric_name: str) -> dict[str, Any]:
    example_sub = "1.1.A.a" if rubric_name.strip().lower() == "rubric_04" else ""
    return {
        "sections": {
            "pedagogy": {
                "criteria": {
                    "1.1": {
                        "deductions": [
                            {
                                "evidence_turns": [1, 2],
                                "sub_criterion_id": example_sub,
                                "reason": "Tutor supplied direct answer pieces.",
                                "points": 4,
                            }
                        ],
                        "score": 8,
                        "max": 12,
                        "name": _CRITERIA_NAME["1.1"],
                    },
                    "1.2": {"deductions": [], "score": 6, "max": 6, "name": _CRITERIA_NAME["1.2"]},
                    "1.3": {"deductions": [], "score": 5, "max": 5, "name": _CRITERIA_NAME["1.3"]},
                },
                "base": {"score": 19, "max": 23},
                "malus": {"id": "1.4", "explanation": "", "score": 0, "max": 2},
            },
            "dialogue": {
                "criteria": {
                    "2.1": {"deductions": [], "score": 4, "max": 4, "name": _CRITERIA_NAME["2.1"]},
                    "2.2": {"deductions": [], "score": 6, "max": 6, "name": _CRITERIA_NAME["2.2"]},
                },
                "base": {"score": 10, "max": 10},
                "malus": {"id": "2.3", "explanation": "", "score": 0, "max": 2},
            },
            "communication": {
                "criteria": {
                    "3.1": {"deductions": [], "score": 6, "max": 6, "name": _CRITERIA_NAME["3.1"]},
                    "3.2": {"deductions": [], "score": 5, "max": 5, "name": _CRITERIA_NAME["3.2"]},
                    "3.3": {"deductions": [], "score": 3, "max": 3, "name": _CRITERIA_NAME["3.3"]},
                },
                "base": {"score": 14, "max": 14},
                "malus": {"id": "3.4", "explanation": "", "score": 0, "max": 2},
            },
        },
        "total_base_score": 43,
        "max_base_score": 47,
        "total_malus": 0,
        "max_malus": 6,
        "max_score": 47,
        "overview": ["Brief evidence-based summary."],
        "total_score": 43,
        "judge_llm_calls": 1,
    }


def load_judge_prompt(*, prompt_name: str = "judge_03", rubric_name: str = "rubric_04") -> str:
    prompt_path = _PROMPTS_DIR / f"{prompt_name}.txt"
    rubric_path = _RUBRICS_DIR / f"{rubric_name}.md"
    if not prompt_path.exists():
        raise JudgeError(f"Prompt file not found: {prompt_path}")
    if not rubric_path.exists():
        raise JudgeError(f"Rubric file not found: {rubric_path}")
    prompt = prompt_path.read_text(encoding="utf-8")
    rubric = rubric_path.read_text(encoding="utf-8")
    schema = json.dumps(_build_expected_schema(rubric_name=rubric_name), ensure_ascii=False, indent=2)
    return prompt.format(rubric=rubric, schema=schema)


def _judge_repair_prompt(error: str) -> str:
    return (
        "Your previous JSON did not validate against the required schema / consistency rules.\n"
        f"Validation error: {error}\n\n"
        "Return corrected JSON ONLY that fixes the error while keeping your original grading intent.\n"
        "Do NOT add extra wrapper keys like `grade`, `result`, or `output`.\n"
        "All required integer totals must be present and non-null: total_score, max_score, "
        "total_base_score, max_base_score, total_malus, max_malus.\n"
        "Ensure all totals and maxima are correct and internally consistent.\n"
    )


def _format_conversation_for_judge(transcript: dict[str, Any]) -> str:
    context = transcript.get("context", "")
    exercise = transcript.get("exercise", "")
    exchanges = transcript.get("exchanges", [])
    lines: list[str] = ["Assignment input:"]
    if str(context).strip():
        lines.append("Context:")
        lines.append(str(context).strip())
        lines.append("")
    lines.append("Exercise:")
    lines.append(str(exercise).strip())
    lines.append("")
    lines.append("Conversation transcript (student+tutor exchanges):")
    for ex in exchanges:
        turn = ex.get("turn")
        lines.append(f"Turn {turn} — Student: {ex.get('student', '')}")
        lines.append(f"Turn {turn} — Tutor: {ex.get('tutor', '')}")
        lines.append("")
    return "\n".join(lines).strip()


def _default_output_path(*, transcript_path: Path, prompt_name: str, rubric_name: str, provider: str) -> Path:
    return transcript_path.with_name(f"{transcript_path.stem}__{prompt_name}__{rubric_name}__{provider}.json")


class _JudgeState(TypedDict):
    attempts: int
    system_prompt: str
    conversation_text: str
    num_turns: int
    last_output: NotRequired[str]
    last_error: NotRequired[str]
    grade_json: NotRequired[dict[str, Any]]


def _create_judge_graph(*, model_name: str, api_key: str, enforce_sub_criterion_ids: bool):
    reasoning = _openai_reasoning_config()
    kwargs: dict[str, Any] = {"model": model_name, "temperature": 0, "api_key": api_key}
    if reasoning:
        kwargs["reasoning"] = reasoning
    model = ChatOpenAI(**kwargs)

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
        try:
            parsed = _parse_json_from_model_output(state.get("last_output", ""))
            parsed = _sanitize_grade_payload(parsed)
            validated = _validate_grade_payload(
                parsed,
                num_turns=int(state["num_turns"]),
                enforce_sub_criterion_ids=enforce_sub_criterion_ids,
            )
            return {"grade_json": _order_grade_payload(validated), "last_error": None}
        except JudgeError as e:
            return {"grade_json": None, "last_error": str(e)}

    graph = StateGraph(_JudgeState)
    graph.add_node("judge", judge_node)
    graph.add_node("validate", validate_node)
    graph.add_edge(START, "judge")
    graph.add_edge("judge", "validate")

    def route(state: _JudgeState) -> str:
        if state.get("grade_json") is not None:
            return END
        return END if int(state.get("attempts", 0)) >= _MAX_ATTEMPTS else "judge"

    graph.add_conditional_edges("validate", route, {"judge": "judge", END: END})
    return graph.compile()


def judge_transcript(
    transcript_name: str,
    *,
    prompt_name: str = "judge_03",
    rubric_name: str = "rubric_04",
    output_name: str | None = None,
) -> JudgeResult:
    name = (transcript_name or "").strip()
    if not name:
        raise JudgeError("transcript_name is required (path without .json).")

    source_path = TRANSCRIPTS_DIR / f"{name}.json"
    if not source_path.exists():
        raise JudgeError(f"Transcript not found: {source_path}")

    try:
        transcript = json.loads(source_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise JudgeError(f"Transcript is not valid JSON: {e}") from e
    if not isinstance(transcript, dict):
        raise JudgeError("Transcript JSON must be an object.")

    exchanges = transcript.get("exchanges")
    if not isinstance(exchanges, list) or not exchanges:
        raise JudgeError("Transcript must contain a non-empty 'exchanges' array.")

    model_name = os.environ.get("OPENAI_MODEL", _DEFAULT_OPENAI_MODEL)
    graph = _create_judge_graph(
        model_name=model_name,
        api_key=_require_openai_api_key(),
        enforce_sub_criterion_ids=rubric_name.strip().lower() == "rubric_04",
    )
    result = graph.invoke(
        {
            "attempts": 0,
            "system_prompt": load_judge_prompt(prompt_name=prompt_name, rubric_name=rubric_name),
            "conversation_text": _format_conversation_for_judge(transcript),
            "num_turns": len(exchanges),
        }
    )
    grade_json = result.get("grade_json")
    if grade_json is None:
        raise JudgeError(f"Judge failed to produce valid grade JSON. Last error: {result.get('last_error')}")

    grade_payload = dict(grade_json)
    grade_payload["model"] = {
        "provider": "openai",
        "model": model_name,
        "temperature": 0,
        "reasoning_effort": _openai_reasoning_effort(),
    }
    grade_payload["judge_llm_calls"] = int(result.get("attempts", 0))
    if _env_truthy("JUDGE_INCLUDE_TIMESTAMP"):
        grade_payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    grade_payload = _order_grade_payload(grade_payload)

    out_transcript = dict(transcript)
    out_transcript.pop("grade", None)
    out_transcript["grade"] = grade_payload

    output_path = (
        _default_output_path(transcript_path=source_path, prompt_name=prompt_name, rubric_name=rubric_name, provider="gpt")
        if output_name is None
        else source_path.with_name(f"{output_name}.json")
    )
    output_path.write_text(json.dumps(out_transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return JudgeResult(
        total_score=int(grade_payload["total_score"]),
        max_score=int(grade_payload["max_score"]),
        output_path=output_path,
    )
