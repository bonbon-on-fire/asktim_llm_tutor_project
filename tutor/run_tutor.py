"""
Humanities LLM Tutor — LangGraph engine.

Provides the tutor graph, system-prompt loading, and response parsing.
Called by the UI and web app; not intended to run standalone.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from typing_extensions import Annotated, TypedDict

import operator

from utils.parsing import extract_json_object

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_REPO_ROOT = Path(__file__).resolve().parent.parent

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


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

def load_system_prompt(
    prompt_name: str = "tutor_01",
    assignment_override: str | None = None,
) -> str:
    """
    Load a tutor system prompt from ``tutor/prompts/<prompt_name>.txt``.

    If *assignment_override* is provided, the ``<Assignment>...</Assignment>``
    block inside the prompt is replaced with the override text.
    """
    path = PROMPTS_DIR / f"{prompt_name}.txt"
    if not path.exists():
        available = sorted(p.stem for p in PROMPTS_DIR.glob("*.txt"))
        raise FileNotFoundError(
            f"Tutor prompt '{prompt_name}' not found at {path}.\n"
            f"Available prompts: {available}"
        )
    text = path.read_text(encoding="utf-8")
    if assignment_override is not None:
        text = re.sub(
            r"<Assignment>.*?</Assignment>",
            f"<Assignment>\n{assignment_override.strip()}\n</Assignment>",
            text,
            flags=re.DOTALL,
        )
    return text.strip()


# ---------------------------------------------------------------------------
# LangGraph state and graph
# ---------------------------------------------------------------------------

class TutorState(TypedDict):
    messages: Annotated[list, operator.add]


def create_tutor_graph(system_prompt: str):
    """Build and compile the LangGraph for the tutor."""
    model = ChatOpenAI(
        model=os.environ.get("OPENAI_MODEL", "gpt-5.2"),
        api_key=_require_openai_api_key(),
    )

    def tutor_node(state: TutorState) -> dict:
        messages = [SystemMessage(content=system_prompt)] + state["messages"]
        response = model.invoke(messages)
        return {"messages": [response]}

    graph = StateGraph(TutorState)
    graph.add_node("tutor", tutor_node)
    graph.add_edge(START, "tutor")
    graph.add_edge("tutor", END)
    return graph.compile()


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

def parse_tutor_response(content: str) -> tuple[str | None, str | None]:
    """
    Extract ``pedagogical-reasoning`` and ``Student-facing-answer`` from
    the tutor's JSON-formatted response.

    Tries three strategies: raw JSON, fenced code block, balanced-brace extraction.
    Returns ``(reasoning, answer)`` — either may be ``None`` on parse failure.
    """
    text = content.strip()
    for candidate in (
        text,
        _fenced_json(text),
        extract_json_object(text),
    ):
        if candidate is None:
            continue
        try:
            data = json.loads(candidate)
            return (
                data.get("pedagogical-reasoning"),
                data.get("Student-facing-answer"),
            )
        except (json.JSONDecodeError, TypeError):
            continue
    return None, None


def _fenced_json(text: str) -> str | None:
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_tutor_reply(
    messages: list,
    assignment_override: str | None = None,
    *,
    graph=None,
    prompt_name: str = "tutor_01",
) -> tuple[list, str]:
    """
    Invoke the tutor with the given conversation history.

    Returns ``(updated_messages, student_facing_answer_text)``.
    """
    if graph is None:
        system_prompt = load_system_prompt(prompt_name, assignment_override)
        graph = create_tutor_graph(system_prompt)
    result = graph.invoke({"messages": messages})
    out_messages = result["messages"]
    last = out_messages[-1] if out_messages else None
    if isinstance(last, AIMessage):
        content = last.content if isinstance(last.content, str) else str(last.content)
        _, student_facing = parse_tutor_response(content)
        text = student_facing if student_facing is not None else content
    else:
        text = ""
    return out_messages, text
