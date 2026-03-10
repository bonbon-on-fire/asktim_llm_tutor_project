"""
Shared student bot engine.

All student personas use the same LangGraph pipeline — only the system prompt
differs.  Select a persona by passing ``prompt_name`` (e.g. "chaotic_01"),
which maps to ``students/personas/<prompt_name>.txt``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Sequence

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from typing_extensions import NotRequired, TypedDict

PERSONAS_DIR = Path(__file__).resolve().parent / "personas"
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
# Prompt loading
# ---------------------------------------------------------------------------

def list_personas() -> list[str]:
    """Return sorted persona names available in students/personas/ (without extension)."""
    return sorted(p.stem for p in PERSONAS_DIR.glob("*.txt"))


def load_prompt(prompt_name: str) -> str:
    """Load a student persona prompt by name (e.g. 'chaotic_01' → personas/chaotic_01.txt)."""
    path = PERSONAS_DIR / f"{prompt_name}.txt"
    if not path.exists():
        available = list_personas()
        raise FileNotFoundError(
            f"Persona '{prompt_name}' not found at {path}.\n"
            f"Available personas: {available}"
        )
    return path.read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# LangGraph state & nodes
# ---------------------------------------------------------------------------

class StudentBotState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    assignment: NotRequired[str]
    turn_size: NotRequired[int]


def _student_role_contract() -> str:
    # Shared hard constraints for all student personas.
    return (
        "ROLE CONTRACT (NON-NEGOTIABLE):\n"
        "- You are the STUDENT speaking to the tutor.\n"
        "- Never act like the tutor.\n"
        "- Never offer tutoring plans, coaching frameworks, or multi-step teaching prompts.\n"
        "- Never phrase as 'we can work on your ...' or similar tutor-led framing.\n"
        "- Use first-person student voice (I/my), and ask for help as a student.\n"
        "- Keep it brief (1-4 sentences)."
    )


def _looks_tutor_like(text: str) -> bool:
    lowered = (text or "").lower()
    markers = (
        "to get started",
        "tell me:",
        "we can work on your",
        "if you paste your rough notes",
        "i can help you tighten",
        "let's work on your",
        "1)",
        "2)",
    )
    return any(m in lowered for m in markers)


def _last_message_is_tutor(state: StudentBotState) -> bool:
    messages = state.get("messages") or []
    return bool(messages) and isinstance(messages[-1], HumanMessage)


def _build_student_agent_node(persona: str, model: ChatOpenAI):
    def student_agent(state: StudentBotState) -> dict:
        messages = state.get("messages") or []
        if not messages:
            return {"messages": [AIMessage(content="[Student has nothing to respond to yet.]")]}
        if not _last_message_is_tutor(state):
            return {}

        system_content = f"{_student_role_contract()}\n\n{persona}"
        assignment = (state.get("assignment") or "").strip()
        turn_size = state.get("turn_size")
        turn_size_text = ""
        if isinstance(turn_size, int) and turn_size > 0:
            turn_size_text = (
                "\n\nPlanned conversation length with the tutor: "
                f"{turn_size} student+tutor exchanges."
            )
        if assignment:
            system_content += (
                "\n\n---\n\n"
                "Current exercise (assignment) you are working on with the tutor:\n\n"
                + assignment
            )
        if turn_size_text:
            system_content += turn_size_text
        chat_messages = [SystemMessage(content=system_content)] + list(messages)
        response = model.invoke(chat_messages)
        if isinstance(response, BaseMessage):
            content = response.content if isinstance(response.content, str) else str(response.content)
            if _looks_tutor_like(content):
                # Retry once with an explicit correction instruction.
                correction = SystemMessage(
                    content=(
                        "Your previous reply sounded like a tutor. "
                        "Rewrite now as a student message to the tutor only. "
                        "No numbered teaching agenda, no tutoring plan."
                    )
                )
                response = model.invoke(chat_messages + [correction])
        if not isinstance(response, BaseMessage):
            response = AIMessage(content=str(response))
        return {"messages": [response]}

    return student_agent


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(
    *,
    prompt_name: str | None = None,
    persona: str | None = None,
    model: ChatOpenAI | None = None,
):
    """
    Build and compile the LangGraph for a student bot.

    Provide either ``prompt_name`` (looks up the .txt file) or ``persona``
    (raw prompt text).  If neither is given, ``prompt_name`` defaults to
    ``"chaotic_01"``.
    """
    if model is None:
        model = ChatOpenAI(
            model=os.environ.get("OPENAI_MODEL", "gpt-5.2"),
            temperature=0.7,
            api_key=_require_openai_api_key(),
        )
    if persona is None:
        persona = load_prompt(prompt_name or "chaotic_01")

    node_fn = _build_student_agent_node(persona, model)
    builder = StateGraph(StudentBotState)
    builder.add_node("student_agent", node_fn)
    builder.add_edge(START, "student_agent")
    builder.add_edge("student_agent", END)
    return builder.compile()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_next_student_message(
    messages: Sequence[BaseMessage],
    *,
    prompt_name: str | None = None,
    assignment: str | None = None,
    turn_size: int | None = None,
    graph=None,
    model: ChatOpenAI | None = None,
    persona: str | None = None,
) -> BaseMessage:
    """
    Return the next student message given the conversation so far.

    The last message in ``messages`` should be from the tutor (HumanMessage).

    Parameters
    ----------
    prompt_name : str
        Persona prompt to use (e.g. "chaotic_01").  Maps to
        ``students/personas/<prompt_name>.txt``.
    assignment : str, optional
        Assignment text the student can reference.
    turn_size : int, optional
        Planned number of student+tutor exchanges for this run.
    graph : optional
        Pre-built graph (skips build_graph).
    model : ChatOpenAI, optional
        Override the default model.
    persona : str, optional
        Raw prompt text (overrides prompt_name).
    """
    if graph is None:
        graph = build_graph(prompt_name=prompt_name, model=model, persona=persona)
    payload: dict = {"messages": list(messages)}
    if assignment is not None:
        payload["assignment"] = assignment.strip()
    if turn_size is not None and turn_size > 0:
        payload["turn_size"] = turn_size
    result = graph.invoke(payload)
    out_messages = result.get("messages") or []
    if not out_messages:
        return AIMessage(content="[No response generated.]")
    return out_messages[-1]
