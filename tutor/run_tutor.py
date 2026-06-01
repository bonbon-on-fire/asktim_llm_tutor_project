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
from langchain_anthropic import ChatAnthropic  # pyright: ignore[reportMissingImports]
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
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
    """Return the OpenAI API key from the environment or raise RuntimeError if absent."""
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY (or OPENAI_KEY) environment variable is required but not set."
        )
    return key


def _require_anthropic_api_key() -> str:
    """Return the Anthropic API key from the environment or raise RuntimeError if absent."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is required but not set."
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
    """LangGraph state carrying the accumulated conversation message list."""

    messages: Annotated[list, operator.add]


def _looks_non_student_like(text: str) -> bool:
    """
    Heuristic check for malformed or non-student input.

    This catches common cases where the incoming message looks like a tutor /
    system artifact instead of a student's chat message.
    """
    lowered = (text or "").strip().lower()
    if not lowered:
        return True
    markers = (
        "role contract",
        "pedagogical-reasoning",
        "student-facing-answer",
        "```json",
        "<assignment>",
        "as an experienced tutor",
        "act as an experienced tutor",
        "step 1:",
        "step 2:",
    )
    return any(m in lowered for m in markers)


def _build_invalid_input_reply() -> AIMessage:
    """
    Return a strict tutor JSON reply asking the student to restate input.
    """
    payload = {
        "pedagogical-reasoning": (
            "The latest input appears malformed or not written in student voice. "
            "I should ask for a clean student message before continuing so guidance "
            "stays accurate and assignment-focused."
        ),
        "Student-facing-answer": (
            "I might be reading a malformed message. Please restate your question as "
            "a student in 1-3 sentences, and include the exact part of the assignment "
            "you want help with."
        ),
    }
    return AIMessage(content=json.dumps(payload, ensure_ascii=False))


def build_tutor_model(provider: str = "gpt"):
    """Construct a LangChain chat model for the tutor.

    Exposed so the streaming path can call ``model.stream(...)`` directly,
    bypassing the LangGraph wrapper used by the non-streaming path.
    """
    if provider == "claude":
        return ChatAnthropic(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            api_key=_require_anthropic_api_key(),
        )
    return ChatOpenAI(
        model=os.environ.get("OPENAI_MODEL", "gpt-5.4"),
        api_key=_require_openai_api_key(),
    )


def create_tutor_graph(system_prompt: str, *, provider: str = "gpt"):
    """Build and compile the LangGraph for the tutor.

    Args:
        system_prompt: The fully-rendered system prompt text.
        provider: ``"gpt"`` (default) uses OpenAI; ``"claude"`` uses Anthropic Claude.
    """
    model = build_tutor_model(provider)

    def tutor_node(state: TutorState) -> dict:
        """Generate one tutor turn from current conversation state."""

        messages = [SystemMessage(content=_sanitize_text_for_transport(system_prompt))]
        state_messages = state.get("messages") or []
        for msg in state_messages:
            messages.append(_sanitize_message_content(msg))
        last = state_messages[-1] if state_messages else None
        if isinstance(last, HumanMessage):
            last_text = last.content if isinstance(last.content, str) else str(last.content)
            if _looks_non_student_like(last_text):
                return {"messages": [_build_invalid_input_reply()]}
        response = model.invoke(messages)
        response = _normalize_tutor_ai_message(response)
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


def _normalize_tutor_ai_message(msg: BaseMessage) -> AIMessage:
    """
    Force tutor output into a strict two-field JSON object.

    This guarantees downstream consumers always see:
    - ``pedagogical-reasoning``
    - ``Student-facing-answer``
    """
    content = msg.content if isinstance(msg.content, str) else str(msg.content)
    reasoning, answer = parse_tutor_response(content)
    payload = {
        "pedagogical-reasoning": (reasoning or "").strip(),
        "Student-facing-answer": (answer or content).strip(),
    }
    if not payload["pedagogical-reasoning"]:
        payload["pedagogical-reasoning"] = (
            "Fallback reasoning generated by runtime: upstream response was not "
            "valid tutor JSON."
        )
    if not payload["Student-facing-answer"]:
        payload["Student-facing-answer"] = (
            "I could not generate a valid response. Please restate your last "
            "message in one or two sentences so I can help."
        )
    normalized = json.dumps(payload, ensure_ascii=False)
    return AIMessage(content=normalized)


def _fenced_json(text: str) -> str | None:
    """Extract JSON content from the first Markdown code fence (```json ... ```) in text."""
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    return m.group(1).strip() if m else None


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


def _sanitize_message_content(msg: BaseMessage) -> BaseMessage:
    """Return a clean copy of msg with control characters stripped from content."""
    content = msg.content if isinstance(msg.content, str) else str(msg.content)
    safe = _sanitize_text_for_transport(content)
    if isinstance(msg, HumanMessage):
        return HumanMessage(content=safe)
    if isinstance(msg, AIMessage):
        return AIMessage(content=safe)
    if isinstance(msg, SystemMessage):
        return SystemMessage(content=safe)
    return HumanMessage(content=safe)


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


# ---------------------------------------------------------------------------
# Streaming support
# ---------------------------------------------------------------------------

class StudentAnswerExtractor:
    """Incrementally pull characters out of the tutor JSON's
    ``Student-facing-answer`` field as raw model tokens arrive.

    The tutor returns a single JSON object with two keys: the hidden
    ``pedagogical-reasoning`` and the visible ``Student-facing-answer``.
    Streaming raw tokens would leak the reasoning and show JSON syntax to
    the student. This extractor walks the accumulating buffer with a small
    state machine and emits only the chars that live inside the answer
    field's string value, with JSON escape handling.

    Usage::

        ex = StudentAnswerExtractor()
        for token in model.stream(messages):
            visible = ex.feed(token.content)
            if visible:
                send_to_client(visible)
    """

    _FIELD = '"Student-facing-answer"'
    _ESCAPE_MAP = {
        "n": "\n",
        "t": "\t",
        "r": "\r",
        '"': '"',
        "\\": "\\",
        "/": "/",
        "b": "\b",
        "f": "\f",
    }

    def __init__(self) -> None:
        self._buffer = ""
        self._pos = 0
        self._phase = "find_field"
        # find_field -> find_colon -> find_open_quote -> in_value -> done
        self._escape = False

    @property
    def found_answer(self) -> bool:
        """True once we've located the answer field's opening quote."""
        return self._phase in ("in_value", "done")

    @property
    def buffer(self) -> str:
        """Full accumulated raw text — needed for final JSON parse."""
        return self._buffer

    def feed(self, chunk: str) -> str:
        """Add ``chunk`` to the buffer and return any newly-visible chars."""
        if not chunk:
            return ""
        self._buffer += chunk
        out: list[str] = []
        while True:
            advanced = self._step(out)
            if not advanced:
                return "".join(out)

    def _step(self, out: list[str]) -> bool:
        """One state-machine iteration. Returns True if state advanced."""
        if self._phase == "find_field":
            idx = self._buffer.find(self._FIELD, self._pos)
            if idx < 0:
                return False
            self._pos = idx + len(self._FIELD)
            self._phase = "find_colon"
            return True

        if self._phase == "find_colon":
            while self._pos < len(self._buffer):
                ch = self._buffer[self._pos]
                if ch in " \t\n\r":
                    self._pos += 1
                    continue
                if ch == ":":
                    self._pos += 1
                    self._phase = "find_open_quote"
                    return True
                # Unexpected — abandon streaming; let the final parse handle it.
                self._phase = "done"
                return True
            return False

        if self._phase == "find_open_quote":
            while self._pos < len(self._buffer):
                ch = self._buffer[self._pos]
                if ch in " \t\n\r":
                    self._pos += 1
                    continue
                if ch == '"':
                    self._pos += 1
                    self._phase = "in_value"
                    return True
                self._phase = "done"
                return True
            return False

        if self._phase == "in_value":
            while self._pos < len(self._buffer):
                ch = self._buffer[self._pos]
                if self._escape:
                    mapped = self._ESCAPE_MAP.get(ch)
                    if mapped is not None:
                        out.append(mapped)
                        self._pos += 1
                        self._escape = False
                        continue
                    if ch == "u":
                        if self._pos + 5 > len(self._buffer):
                            # Need 4 hex chars after 'u'; wait for next chunk.
                            return False
                        hex_str = self._buffer[self._pos + 1 : self._pos + 5]
                        try:
                            out.append(chr(int(hex_str, 16)))
                        except ValueError:
                            pass
                        self._pos += 5
                        self._escape = False
                        continue
                    out.append(ch)
                    self._pos += 1
                    self._escape = False
                    continue

                if ch == "\\":
                    if self._pos + 1 >= len(self._buffer):
                        return False  # need the escape companion char
                    self._escape = True
                    self._pos += 1
                    continue
                if ch == '"':
                    self._pos += 1
                    self._phase = "done"
                    return False
                out.append(ch)
                self._pos += 1
            return False

        # done
        return False


def stream_tutor_reply(
    messages: list,
    *,
    model,
    system_prompt: str,
):
    """Yield visible answer chunks, then a final ``("__done__", full_json)`` tuple.

    Bypasses the LangGraph wrapper so we can use ``model.stream(...)`` directly.
    Mirrors the non-student-like guard from ``tutor_node`` so a malformed
    incoming message gets the canned reply (delivered as a single delta).

    Yields:
        ``str`` for each batch of visible chars to emit to the client.
        Finally ``("__done__", full_raw_json)`` so callers can run
        :func:`parse_tutor_response` to recover the hidden reasoning.
    """
    safe_system = _sanitize_text_for_transport(system_prompt)
    safe_messages = [SystemMessage(content=safe_system)]
    for msg in messages:
        safe_messages.append(_sanitize_message_content(msg))

    last = messages[-1] if messages else None
    if isinstance(last, HumanMessage):
        last_text = last.content if isinstance(last.content, str) else str(last.content)
        if _looks_non_student_like(last_text):
            canned = _build_invalid_input_reply()
            canned_json = canned.content if isinstance(canned.content, str) else str(canned.content)
            _, answer = parse_tutor_response(canned_json)
            if answer:
                yield answer
            yield ("__done__", canned_json)
            return

    extractor = StudentAnswerExtractor()
    try:
        for chunk in model.stream(safe_messages):
            piece = chunk.content if hasattr(chunk, "content") else str(chunk)
            if not isinstance(piece, str):
                piece = str(piece)
            visible = extractor.feed(piece)
            if visible:
                yield visible
    except Exception:
        # If the stream blows up partway, the caller decides what to do; we
        # surface what we've accumulated so persistence isn't a total loss.
        raise
    finally:
        pass

    raw = extractor.buffer
    # Normalize through _normalize_tutor_ai_message so downstream consumers
    # always see the strict two-field JSON shape — same guarantee as the
    # non-streaming path.
    normalized = _normalize_tutor_ai_message(AIMessage(content=raw))
    normalized_text = normalized.content if isinstance(normalized.content, str) else str(normalized.content)

    # Fallback: if our incremental extractor never found the answer field
    # (drifted JSON shape, unusual key ordering, etc.), emit the recovered
    # student-facing answer now so the client still sees something.
    if not extractor.found_answer:
        _, answer = parse_tutor_response(normalized_text)
        if answer:
            yield answer

    yield ("__done__", normalized_text)
