"""Claude-based judge for humanities tutor transcripts."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from typing_extensions import NotRequired, TypedDict

from judge.run_judge_gpt import (
    JudgeError,
    JudgeResult,
    TRANSCRIPTS_DIR,
    _default_output_path,
    _env_truthy,
    _format_conversation_for_judge,
    _judge_repair_prompt,
    _order_grade_payload,
    _parse_json_from_model_output,
    _sanitize_grade_payload,
    _validate_grade_payload,
    load_judge_prompt,
)

_DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-6"
_MAX_ATTEMPTS = 3


def _require_anthropic_api_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise JudgeError("ANTHROPIC_API_KEY environment variable is required but not set.")
    return key


class _JudgeState(TypedDict):
    attempts: int
    system_prompt: str
    conversation_text: str
    num_turns: int
    last_output: NotRequired[str]
    last_error: NotRequired[str]
    grade_json: NotRequired[dict[str, Any]]


def _create_judge_graph(*, model_name: str, api_key: str, enforce_sub_criterion_ids: bool):
    model = ChatAnthropic(model=model_name, temperature=0, api_key=api_key)

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

    model_name = os.environ.get("ANTHROPIC_MODEL", _DEFAULT_ANTHROPIC_MODEL)
    graph = _create_judge_graph(
        model_name=model_name,
        api_key=_require_anthropic_api_key(),
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
    grade_payload["model"] = {"provider": "anthropic", "model": model_name, "temperature": 0}
    grade_payload["judge_llm_calls"] = int(result.get("attempts", 0))
    if _env_truthy("JUDGE_INCLUDE_TIMESTAMP"):
        grade_payload["timestamp_utc"] = datetime.now(timezone.utc).isoformat()
    grade_payload = _order_grade_payload(grade_payload)

    out_transcript = dict(transcript)
    out_transcript.pop("grade", None)
    out_transcript["grade"] = grade_payload

    output_path = (
        _default_output_path(transcript_path=source_path, prompt_name=prompt_name, rubric_name=rubric_name, provider="claude")
        if output_name is None
        else source_path.with_name(f"{output_name}.json")
    )
    output_path.write_text(json.dumps(out_transcript, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return JudgeResult(
        total_score=int(grade_payload["total_score"]),
        max_score=int(grade_payload["max_score"]),
        output_path=Path(output_path),
    )
