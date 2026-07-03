"""
Shared student bot engine.

All student personas use the same LangGraph pipeline — only the system prompt
differs.  Select a persona by passing ``prompt_name`` (e.g. "chaotic"),
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

from utils.figures import build_multimodal_content

PERSONAS_DIR = Path(__file__).resolve().parent / "personas"
_REPO_ROOT = Path(__file__).resolve().parent.parent

# Load repo-level .env once so OPENAI_API_KEY is available across entrypoints.
load_dotenv(_REPO_ROOT / ".env")

# ---------------------------------------------------------------------------
# API key
# ---------------------------------------------------------------------------

def _require_openai_api_key() -> str:
    """Return the OpenAI API key from the environment or raise RuntimeError if absent."""
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY environment variable is required but not set."
        )
    return key


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

def list_personas() -> list[str]:
    """Return sorted persona names available in students/personas/ (without extension)."""
    return sorted(p.stem for p in PERSONAS_DIR.glob("*.txt"))


def load_prompt(prompt_name: str) -> str:
    """Load a student persona prompt by name (e.g. 'chaotic' → personas/chaotic.txt)."""
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
    """LangGraph state for the student bot, carrying messages, optional assignment text, and planned turn count."""

    messages: Annotated[list[BaseMessage], add_messages]
    assignment: NotRequired[str]
    turn_size: NotRequired[int]
    figures: NotRequired[list]


def _student_role_contract() -> str:
    """Return the shared non-negotiable role constraint prompt injected into every student persona."""
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
    """Heuristic check: return True if the text exhibits tutor-like framing markers (numbered agendas, tutoring language, etc.)."""
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
    """True if the last message in state is a HumanMessage (the tutor's turn in the reversed message convention)."""
    messages = state.get("messages") or []
    return bool(messages) and isinstance(messages[-1], HumanMessage)


def _build_student_agent_node(persona: str, model: ChatOpenAI):
    """Return a LangGraph node function that generates the next student message given the conversation state."""
    def student_agent(state: StudentBotState) -> dict:
        """Emit a single student reply when the previous turn was authored by the tutor."""

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
        chat_messages = [SystemMessage(content=_sanitize_text_for_transport(system_content))]
        chat_messages.extend(_sanitize_message_content(m) for m in messages)
        figures = state.get("figures")
        if figures:
            _attach_figures_to_last_human(chat_messages, figures)
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


def _sanitize_text_for_transport(text: str) -> str:
    """
    Remove problematic code points that can break JSON request encoding.

    Keeps common whitespace (tab/newline/carriage return), strips other control
    chars and UTF-16 surrogate code points.
    """
    if not isinstance(text, str):
        text = str(text)
    out_chars: list[str] = []
    for ch in text:
        code = ord(ch)
        if ch in ("\t", "\n", "\r"):
            out_chars.append(ch)
            continue
        if code < 0x20:
            continue
        if 0xD800 <= code <= 0xDFFF:
            continue
        out_chars.append(ch)
    return "".join(out_chars)


def _content_text(content) -> str:
    """Extract the plain-text portion of string or multimodal-list content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return " ".join(p for p in parts if p)
    return str(content)


def _sanitize_content(content):
    """Strip control characters from string or multimodal-list content.

    Text blocks are sanitized; ``image_url`` (and any other) blocks pass through.
    """
    if isinstance(content, list):
        out: list = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                out.append({**block, "text": _sanitize_text_for_transport(block.get("text", ""))})
            else:
                out.append(block)
        return out
    text = content if isinstance(content, str) else str(content)
    return _sanitize_text_for_transport(text)


def _attach_figures_to_last_human(messages: list, figures: list) -> None:
    """Rewrite the last HumanMessage in *messages* to carry *figures* as multimodal content.

    The student responds to the tutor's latest turn (a HumanMessage in this
    bot's reversed-role convention); attaching the exercise figures there lets
    the student reason over the same image the tutor sees. Mutates in place.
    """
    for j in range(len(messages) - 1, -1, -1):
        if isinstance(messages[j], HumanMessage):
            text = _content_text(messages[j].content)
            messages[j] = HumanMessage(content=build_multimodal_content(text, figures))
            return


def _sanitize_message_content(msg: BaseMessage) -> BaseMessage:
    """Return a clean copy of msg with control characters stripped from content.

    Handles both plain-string and multimodal-list content.
    """
    safe = _sanitize_content(msg.content)
    if isinstance(msg, HumanMessage):
        return HumanMessage(content=safe)
    if isinstance(msg, AIMessage):
        return AIMessage(content=safe)
    if isinstance(msg, SystemMessage):
        return SystemMessage(content=safe)
    return HumanMessage(content=safe)


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
    ``"chaotic"``.
    """
    if model is None:
        model = ChatOpenAI(
            model=os.environ.get("OPENAI_MODEL", "gpt-5.4"),
            temperature=0.7,
            api_key=_require_openai_api_key(),
        )
    if persona is None:
        persona = load_prompt(prompt_name or "chaotic")

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
    figures: list | None = None,
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
        Persona prompt to use (e.g. "chaotic").  Maps to
        ``students/personas/<prompt_name>.txt``.
    assignment : str, optional
        Assignment text the student can reference.
    turn_size : int, optional
        Planned number of student+tutor exchanges for this run.
    figures : list, optional
        Figure paths (or bytes) for the current exercise; attached to the
        tutor's latest turn as multimodal content so the student can see them.
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
    if figures:
        payload["figures"] = figures
    result = graph.invoke(payload)
    out_messages = result.get("messages") or []
    if not out_messages:
        return AIMessage(content="[No response generated.]")
    return out_messages[-1]
