"""
Humanities LLM Tutor — LangGraph engine.

Provides the tutor graph, system-prompt loading, and response parsing.
Called by the UI and web app; not intended to run standalone.
"""

from __future__ import annotations

import anthropic
import base64
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

from tutor.json_mode import (
    TUTOR_TOOL_NAME,
    anthropic_tool_kwargs,
    anthropic_tools,
    json_mode_enabled,
    openai_response_format,
)
from utils.figures import build_multimodal_content
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
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError(
            "OPENAI_API_KEY environment variable is required but not set."
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
        # Use a replacement *function* so backslashes in the assignment (e.g.
        # LaTeX like \sum, \leq) are inserted literally — a template string would
        # make re.sub interpret them as escapes ("bad escape \s").
        replacement = f"<Assignment>\n{assignment_override.strip()}\n</Assignment>"
        text = re.sub(
            r"<Assignment>.*?</Assignment>",
            lambda _m: replacement,
            text,
            flags=re.DOTALL,
        )
    return text.strip()


# ---------------------------------------------------------------------------
# LangGraph state and graph
# ---------------------------------------------------------------------------

class TutorState(TypedDict, total=False):
    """LangGraph state: the accumulated message list plus this turn's RAG context.

    ``retrieved_context`` (optional) is the per-turn RAG grounding folded into the
    system message by ``tutor_node``; absent/empty outside RAG mode.
    """

    messages: Annotated[list, operator.add]
    retrieved_context: str


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
        # max_tokens is set explicitly: langchain-anthropic's model profile
        # doesn't know claude-sonnet-5 yet and falls back to a low 4096, which can
        # truncate long tutor replies (markdown tables + LaTeX). thinking is
        # disabled because the tutor streams a strict two-field JSON via a
        # character-level extractor — adaptive thinking (Sonnet 5's default)
        # would emit thinking blocks that corrupt the stream and burn the token
        # budget, and the tutor already reasons in-band via pedagogical-reasoning.
        return ChatAnthropic(
            model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
            api_key=_require_anthropic_api_key(),
            max_tokens=8192,
            thinking={"type": "disabled"},
            # Emit token-usage metadata while streaming so the streaming chat path
            # can be cost-accounted (default True on Anthropic; explicit for parity).
            stream_usage=True,
        )
    return ChatOpenAI(
        model=os.environ.get("OPENAI_MODEL", "gpt-5.4"),
        api_key=_require_openai_api_key(),
        # OpenAI omits usage from streams unless asked; on so streaming turns are
        # cost-accounted like the non-streaming path.
        stream_usage=True,
    )


def create_tutor_graph(system_prompt: str, *, provider: str = "gpt", figures: list | None = None):
    """Build and compile the LangGraph for the tutor.

    Args:
        system_prompt: The fully-rendered system prompt text.
        provider: ``"gpt"`` (default) uses OpenAI; ``"claude"`` uses Anthropic Claude.
        figures: optional list of figure paths (or bytes) for the current
            exercise. When present, the figures are attached to the latest
            student turn as multimodal content so the tutor can reason over the
            real image. Figures are constant for a conversation, so binding them
            here at graph-build time means each tutor turn re-sends exactly one
            copy attached to the current student message.
    """
    model = build_tutor_model(provider)

    def tutor_node(state: TutorState) -> dict:
        """Generate one tutor turn from current conversation state."""

        messages = [
            _build_system_message(system_prompt, model, state.get("retrieved_context", ""))
        ]
        state_messages = state.get("messages") or []
        for msg in state_messages:
            messages.append(_sanitize_message_content(msg))
        last = state_messages[-1] if state_messages else None
        if isinstance(last, HumanMessage):
            last_text = _content_text(last.content)
            if _looks_non_student_like(last_text):
                return {"messages": [_build_invalid_input_reply()]}
        if figures:
            _attach_figures_to_last_human(messages, figures)
        _cache_last_message(messages, model)
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

    Parses with ``strict=False`` so literal control characters (newlines, tabs)
    inside the JSON string values are tolerated. The model routinely emits
    multi-line markdown tables in ``Student-facing-answer`` with real newlines
    rather than escaped ``\\n``; strict parsing would reject those as invalid
    JSON, and the fallback would then leak the raw ``pedagogical-reasoning`` into
    the student-facing text.
    """
    text = content.strip()
    raw_candidates = [text, _fenced_json(text), extract_json_object(text)]
    # Fallback: the tutor is told to double LaTeX backslashes so the JSON stays
    # valid, but it's inconsistent — a single-backslash "\(" is an invalid JSON
    # escape that makes json.loads reject the whole reply (leaking raw JSON to the
    # student). Repair stray backslashes ONLY after the pristine candidates fail,
    # so well-formed replies are never altered.
    candidates = raw_candidates + [
        _repair_latex_json(c) for c in raw_candidates if c is not None
    ]
    for candidate in candidates:
        if candidate is None:
            continue
        try:
            data = json.loads(candidate, strict=False)
            answer = data.get("Student-facing-answer")
            if isinstance(answer, str):
                answer = _collapse_over_escaped_newlines(answer)
            return (data.get("pedagogical-reasoning"), answer)
        except (json.JSONDecodeError, TypeError):
            continue
    return None, None


def _collapse_over_escaped_newlines(s: str) -> str:
    r"""Turn a literal backslash-n (from an over-escaped ``\\n``) back into a newline.

    The tutor is told to double LaTeX backslashes so its JSON stays valid, and
    sometimes over-applies that to newlines — emitting ``\\n`` where it means a
    line break. That is valid JSON for a literal backslash-n, so ``json.loads``
    yields the two visible chars ``\n`` instead of a newline and the student sees
    a literal ``\n``. Collapse a backslash-n to a real newline UNLESS the ``n``
    begins a LaTeX command (followed by a lowercase letter, e.g. ``\nu``, ``\ne``,
    ``\nabla``) — the mirror of the heuristic in :func:`_repair_latex_json`.
    """
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        if (
            s[i] == "\\"
            and i + 1 < n
            and s[i + 1] == "n"
            and not (i + 2 < n and s[i + 2].islower())
        ):
            out.append("\n")
            i += 2
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _is_hex4(s: str, j: int) -> bool:
    """True if s[j:j+4] is exactly four hex digits (a JSON ``\\uXXXX`` escape)."""
    return len(s) >= j + 4 and all(c in "0123456789abcdefABCDEF" for c in s[j : j + 4])


def _repair_latex_json(s: str) -> str:
    r"""Double stray LaTeX backslashes so an otherwise-invalid tutor JSON parses.

    The tutor writes math as ``\(...\)`` / ``\frac{}{}`` and is *supposed* to
    double each backslash so the JSON stays valid, but often emits a single one —
    an invalid JSON escape that makes ``json.loads`` reject the whole reply.

    This doubles every backslash EXCEPT the escapes the tutor actually intends,
    which are left intact: ``\\`` (literal backslash), ``\"`` (quote), ``\uXXXX``
    (unicode), and ``\n`` when it's a real newline — i.e. not followed by a
    lowercase letter, which would make it a LaTeX command like ``\nu`` / ``\ne``.
    So ``\(``, ``\sum``, ``\le``, ``\frac``, ``\times``, ``\theta`` all survive as
    LaTeX while newlines (markdown tables, paragraphs) stay newlines. ``\t``/``\r``
    are treated as LaTeX (``\times``/``\rho``) — a literal tab/CR in tutor prose is
    vanishingly rare. Used only as a fallback after a strict parse fails, so
    well-formed replies are never passed through it.
    """
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch != "\\" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue
        nxt = s[i + 1]
        keep = (
            nxt in ('"', "\\")
            or (nxt == "n" and not (i + 2 < n and s[i + 2].islower()))
            or (nxt == "u" and _is_hex4(s, i + 2))
        )
        if keep:
            out.append(ch)
            out.append(nxt)
            i += 2
        else:
            out.append("\\\\")
            i += 1
    return "".join(out)


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
    # Preserve token-usage and provider metadata from the raw model response — the
    # normalized message replaces it in the graph output, and cost accounting reads
    # usage_metadata / response_metadata off the final message.
    return AIMessage(
        content=normalized,
        usage_metadata=getattr(msg, "usage_metadata", None),
        response_metadata=getattr(msg, "response_metadata", None) or {},
    )


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


def _content_text(content) -> str:
    """Extract the plain-text portion of a message's content.

    Content may be a plain string or a list of multimodal blocks
    (``{"type": "text", ...}`` / ``{"type": "image_url", ...}``). Image blocks
    contribute no text. Used for heuristics and parsing that only care about
    the textual part.
    """
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
    """Strip control characters from string or multimodal list content.

    Plain strings are sanitized directly. For multimodal lists, the text of
    each ``text`` block is sanitized while ``image_url`` (and any other) blocks
    pass through untouched, preserving the multimodal shape.
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

    Mutates *messages* in place. No-op when there is no HumanMessage to attach to.
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


def _build_system_message(
    system_prompt: str, model, retrieved_context: str = ""
) -> SystemMessage:
    """Build the tutor system message, prompt-cached on Anthropic.

    The system prompt (assignment context: about + course/syllabus/lectures +
    exercise) is large and constant across every turn of a conversation, so it is
    the ideal prompt-cache target. Anthropic (Claude) does not cache unless the
    block is explicitly marked with ``cache_control``, so we mark it here — the
    cached prefix is reused on every subsequent turn (and across conversations
    that share the same prompt) within the cache TTL, at a fraction of the input
    cost. OpenAI caches long prefixes automatically, so a plain string is left
    as-is there (and for any other provider). Marking is billing/latency-only —
    it never changes the model's output. Anthropic silently ignores the marker
    when the prompt is under its minimum cacheable length, so this is always safe.

    ``retrieved_context`` is this turn's RAG grounding (empty outside RAG mode).
    It's delivered here, in the tutor's instruction channel, rather than glued
    onto the student's turn — but it MUST land AFTER the static, cacheable prompt
    so caching still hits on the unchanging prefix and only the fresh RAG is
    re-read each turn. On Anthropic that means a SECOND, uncached block after the
    cache_control breakpoint; on OpenAI it's appended to the string, keeping the
    static part as the (auto-cached) prefix.
    """
    text = _sanitize_text_for_transport(system_prompt)
    rag = _sanitize_text_for_transport(retrieved_context) if retrieved_context else ""
    if isinstance(model, ChatAnthropic):
        blocks: list = [
            {"type": "text", "text": text, "cache_control": {"type": "ephemeral"}}
        ]
        if rag:
            blocks.append({"type": "text", "text": rag})
        return SystemMessage(content=blocks)
    if rag:
        text = f"{text}\n\n{rag}"
    return SystemMessage(content=text)


def _cache_last_message(messages: list, model) -> None:
    """Mark the final message with an ephemeral cache breakpoint (Anthropic only).

    Prompt caching is a prefix match: marking the newest turn writes the whole
    conversation-so-far to cache, so the *next* turn re-reads that prefix at ~0.1x
    input cost instead of re-billing the growing history at full price. Pairs with
    the cached system prefix (2 breakpoints, under Anthropic's limit of 4). OpenAI
    auto-caches long prefixes, so this is a no-op there. Billing/latency only — it
    never changes the model's output, and Anthropic ignores the marker below its
    minimum cacheable length, so it is always safe.
    """
    if not isinstance(model, ChatAnthropic) or not messages:
        return
    content = messages[-1].content
    if isinstance(content, str):
        if not content.strip():
            return
        blocks: list = [{"type": "text", "text": content}]
    elif isinstance(content, list) and content:
        blocks = [b if isinstance(b, dict) else {"type": "text", "text": str(b)} for b in content]
    else:
        return
    blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
    messages[-1] = messages[-1].model_copy(update={"content": blocks})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_tutor_reply(
    messages: list,
    assignment_override: str | None = None,
    *,
    graph=None,
    prompt_name: str = "tutor_01",
    figures: list | None = None,
    retrieved_context: str = "",
) -> tuple[list, str]:
    """
    Invoke the tutor with the given conversation history.

    Returns ``(updated_messages, student_facing_answer_text)``.

    *figures* is only used when this function builds its own graph; when a
    pre-built *graph* is supplied, bind figures via :func:`create_tutor_graph`.

    *retrieved_context* is this turn's RAG grounding; it rides in the graph state
    and ``tutor_node`` folds it into the system message (empty outside RAG mode).
    """
    if graph is None:
        system_prompt = load_system_prompt(prompt_name, assignment_override)
        graph = create_tutor_graph(system_prompt, figures=figures)
    result = graph.invoke({"messages": messages, "retrieved_context": retrieved_context})
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

def _apply_json_mode(model):
    """Bind API-level structured-output enforcement to *model* when the gate is on.

    Claude -> force the ``tutor_reply`` tool; OpenAI -> strict ``response_format``.
    Applied at the call site (not at model-build time) so the cached model stays a
    plain ``ChatAnthropic``/``ChatOpenAI`` — the prompt-cache helpers key off
    ``isinstance(model, ChatAnthropic)`` and must not see a ``RunnableBinding``.
    Gate off, or an unknown model type, returns *model* unchanged.
    """
    if not json_mode_enabled():
        return model
    if isinstance(model, ChatAnthropic):
        return model.bind_tools(anthropic_tools(), tool_choice=TUTOR_TOOL_NAME)
    if isinstance(model, ChatOpenAI):
        return model.bind(response_format=openai_response_format())
    return model


def _chunk_json_fragment(chunk) -> str:
    """Return the JSON text fragment carried by a langchain ``AIMessageChunk``.

    OpenAI (text / ``response_format``) puts it in ``.content``; a tool-forced
    Claude chunk leaves ``.content`` empty and streams the tool input via
    ``.tool_call_chunks`` args. Either way the fragment has the same
    ``{"pedagogical-reasoning":…,"Student-facing-answer":…}`` shape the extractor
    already walks."""
    piece = getattr(chunk, "content", "")
    if not isinstance(piece, str):
        piece = ""
    if piece:
        return piece
    parts: list[str] = []
    for tcc in getattr(chunk, "tool_call_chunks", None) or []:
        args = tcc.get("args") if isinstance(tcc, dict) else None
        if args:
            parts.append(args)
    return "".join(parts)


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
    # Only the escapes the tutor actually intends. "b"/"f" are deliberately
    # omitted: a lone "\b"/"\f" is almost always LaTeX (\beta, \frac), not a
    # backspace/formfeed, so they fall through to the "preserve backslash" branch.
    _ESCAPE_MAP = {
        "n": "\n",
        "t": "\t",
        "r": "\r",
        '"': '"',
        "\\": "\\",
        "/": "/",
    }

    def __init__(self) -> None:
        """Initialize an empty buffer and start the parser in the ``find_field`` phase."""
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
                    # Over-escaped newline: a decoded literal backslash ("\\")
                    # immediately followed by "n" (not a LaTeX \n-command) means
                    # the tutor doubled a newline escape. Emit a real newline so
                    # the student doesn't see a literal "\n". Wait for the char
                    # after "n" before deciding, so a chunk boundary can't force a
                    # premature literal backslash.
                    if ch == "\\":
                        if self._pos + 1 >= len(self._buffer):
                            return False  # might be "\\n"; wait for the next char
                        if self._buffer[self._pos + 1] == "n":
                            if self._pos + 2 >= len(self._buffer):
                                return False  # need the char after "n" to decide
                            if not self._buffer[self._pos + 2].islower():
                                out.append("\n")
                                self._pos += 2
                                self._escape = False
                                continue
                        out.append("\\")
                        self._pos += 1
                        self._escape = False
                        continue
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
                    # Unmapped escape (e.g. "\(", "\f" in \frac): the tutor meant a
                    # literal LaTeX backslash, not a JSON escape — keep both chars
                    # so KaTeX still sees "\(", "\frac", etc.
                    out.append("\\")
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
    retrieved_context: str = "",
):
    """Yield visible answer chunks, then a final ``("__done__", full_json, msg)`` tuple.

    Bypasses the LangGraph wrapper so we can use ``model.stream(...)`` directly.
    Mirrors the non-student-like guard from ``tutor_node`` so a malformed
    incoming message gets the canned reply (delivered as a single delta).

    *retrieved_context* is this turn's RAG grounding, folded into the system
    message (after the cacheable prompt) rather than onto the student's turn.

    Yields:
        ``str`` for each batch of visible chars to emit to the client.
        Finally ``("__done__", full_raw_json, ai_message)`` where ``ai_message``
        is the terminal ``AIMessage`` carrying ``usage_metadata`` /
        ``response_metadata`` (for cost accounting); callers run
        :func:`parse_tutor_response` on ``full_raw_json`` to recover the hidden
        reasoning. The canned-reply path carries no usage (no model call ran).
    """
    safe_messages = [_build_system_message(system_prompt, model, retrieved_context)]
    for msg in messages:
        safe_messages.append(_sanitize_message_content(msg))

    last = messages[-1] if messages else None
    if isinstance(last, HumanMessage):
        last_text = _content_text(last.content)
        if _looks_non_student_like(last_text):
            canned = _build_invalid_input_reply()
            canned_json = canned.content if isinstance(canned.content, str) else str(canned.content)
            _, answer = parse_tutor_response(canned_json)
            if answer:
                yield answer
            yield ("__done__", canned_json, canned)
            return

    _cache_last_message(safe_messages, model)
    extractor = StudentAnswerExtractor()
    # Accumulate the streamed chunks so we recover the turn's token-usage /
    # provider metadata for cost accounting (AIMessageChunk supports +).
    full_chunk = None
    try:
        for chunk in _apply_json_mode(model).stream(safe_messages):
            full_chunk = chunk if full_chunk is None else full_chunk + chunk
            piece = _chunk_json_fragment(chunk)
            visible = extractor.feed(piece)
            if visible:
                yield visible
    except Exception:
        # If the stream blows up partway, the caller decides what to do; we
        # surface what we've accumulated so persistence isn't a total loss.
        raise

    raw = extractor.buffer
    # Normalize through _normalize_tutor_ai_message so downstream consumers always
    # see the strict two-field JSON shape — same guarantee as the non-streaming
    # path. The reply text comes from the extractor buffer (authoritative); the
    # token-usage / response metadata is carried over from the aggregated stream
    # chunk so streaming turns are cost-accounted like non-streaming ones.
    normalized = _normalize_tutor_ai_message(
        AIMessage(
            content=raw,
            usage_metadata=getattr(full_chunk, "usage_metadata", None),
            response_metadata=getattr(full_chunk, "response_metadata", None) or {},
        )
    )
    normalized_text = normalized.content if isinstance(normalized.content, str) else str(normalized.content)

    # Fallback: if our incremental extractor never found the answer field
    # (drifted JSON shape, unusual key ordering, etc.), emit the recovered
    # student-facing answer now so the client still sees something.
    if not extractor.found_answer:
        _, answer = parse_tutor_response(normalized_text)
        if answer:
            yield answer

    yield ("__done__", normalized_text, normalized)


_ROLE_MAP = {"student": "user", "tutor": "assistant", "rag": "system"}
_CACHE_EVERY = 15  # keep the incremental read within Anthropic's 20-block lookback
_MAX_MSG_BREAKPOINTS = 3  # Anthropic allows 4 cache_control blocks/request; the static system block uses 1


def _anthropic_image_blocks(images):
    """Convert ``(bytes, mime)`` image tuples into Anthropic base64 image blocks."""
    blocks = []
    for data, mime in images or []:
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime,
                "data": base64.b64encode(data).decode("ascii"),
            },
        })
    return blocks


def build_anthropic_request(plan, images=None, images_by_student=None):
    """Convert a (role, content) plan into (system_blocks, messages) for the raw
    anthropic Messages API. Static system is a cache-marked text block; message-level
    cache_control breakpoints are tail-anchored and bounded (<= _MAX_MSG_BREAKPOINTS).

    Images (``(bytes, mime)`` tuples) attach to student turns as base64 image blocks
    so pasted tables / screenshots reach the model in cached mode. Two forms:

    - *images_by_student*: a list aligned to the plan's ``student`` steps in order
      (index 0 = first student turn, ..., last = current turn). Each entry is that
      turn's image tuples (``[]`` for none). This replays a PRIOR turn's images too,
      not just the current turn's — so an earlier screenshot stays visible on later
      turns. Takes precedence when given.
    - *images* (legacy): a single flat list attached to the CURRENT student turn
      (the last ``student`` step) only. Used when ``images_by_student`` is None.

    With no images either way the output is byte-identical to the text-only path."""
    static = ""
    steps = []  # (mapped_role, content, is_student)
    for role, content in plan:
        if role == "system_static":
            static = content
        else:
            steps.append((_ROLE_MAP[role], _sanitize_text_for_transport(content), role == "student"))
    student_step_indices = [i for i, (_r, _c, is_student) in enumerate(steps) if is_student]
    # Precompute the image blocks to attach at each step index. `images_by_student`
    # (per-turn, replays prior turns) wins; else fall back to the legacy flat
    # `images` on the last student step only.
    blocks_by_step: dict[int, list] = {}
    if images_by_student is not None:
        for k, step_i in enumerate(student_step_indices):
            turn_images = images_by_student[k] if k < len(images_by_student) else None
            blocks = _anthropic_image_blocks(turn_images)
            if blocks:
                blocks_by_step[step_i] = blocks
    elif student_step_indices:
        blocks = _anthropic_image_blocks(images)
        if blocks:
            blocks_by_step[student_step_indices[-1]] = blocks
    system_blocks = [{"type": "text", "text": _sanitize_text_for_transport(static),
                      "cache_control": {"type": "ephemeral"}}]
    n = len(steps)
    # Tail-anchored rolling breakpoints: the last block plus up to
    # _MAX_MSG_BREAKPOINTS-1 earlier blocks spaced _CACHE_EVERY back from the
    # tail. Bounded at _MAX_MSG_BREAKPOINTS so the total with the static system
    # block never exceeds Anthropic's 4-breakpoint cap, and they roll forward as
    # the conversation grows (staying within the 20-block cache lookback).
    marks = set()
    for k in range(_MAX_MSG_BREAKPOINTS):
        idx = n - 1 - k * _CACHE_EVERY
        if idx >= 0:
            marks.add(idx)
    messages = []
    for i, (role, content, _is_student) in enumerate(steps):
        marked = i in marks
        step_images = blocks_by_step.get(i)
        if not marked and not step_images:
            messages.append({"role": role, "content": content})
            continue
        text_block = {"type": "text", "text": content}
        if marked:
            text_block["cache_control"] = {"type": "ephemeral"}
        content_blocks = [text_block]
        if step_images:
            content_blocks.extend(step_images)
        messages.append({"role": role, "content": content_blocks})
    return system_blocks, messages


def _anthropic_usage_message(message) -> AIMessage:
    """Wrap a raw-anthropic final ``Message``'s usage into an ``AIMessage`` shaped
    like the langchain tutor message, so ``utils.pricing`` can price it.

    Anthropic reports ``input_tokens`` EXCLUDING cache read/write; langchain and
    the pricing formula expect ``input_tokens`` to INCLUDE them (it subtracts
    them to recover the full-price remainder), so we add them back here. Missing
    usage degrades to an empty message → zero cost, never a crash.
    """
    usage = getattr(message, "usage", None)
    if usage is None:
        return AIMessage(content="")
    cache_read = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    cache_write = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    input_tokens = int(getattr(usage, "input_tokens", 0) or 0) + cache_read + cache_write
    output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
    return AIMessage(
        content="",
        usage_metadata={
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "input_token_details": {"cache_read": cache_read, "cache_creation": cache_write},
        },
        response_metadata={"model": getattr(message, "model", None) or model_name},
    )


def _tool_input_from_message(message) -> dict | None:
    """Return the forced ``tutor_reply`` tool call's ``input`` dict, or None.

    The raw-SDK final ``Message`` carries content blocks; under tool-forcing the
    answer lives in the ``tool_use`` block's already-parsed ``input`` (guaranteed
    valid JSON — no repair needed)."""
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TUTOR_TOOL_NAME:
            inp = getattr(block, "input", None)
            if isinstance(inp, dict):
                return inp
    return None


def stream_tutor_reply_anthropic_raw(plan, *, model_name, api_key, images=None, images_by_student=None):
    """Stream a cached-mode tutor reply via the raw anthropic SDK (langchain
    rejects the interleaved multi-system structure). Same yield contract as the
    langchain ``stream_tutor_reply``: visible str chunks, then
    ``('__done__', normalized_json, usage_msg)`` where ``usage_msg`` is an
    ``AIMessage`` carrying ``usage_metadata`` / ``response_metadata`` for cost
    accounting (see :func:`_anthropic_usage_message`).

    Images (``(bytes, mime)`` tuples) attach to student turns as base64 image
    blocks so pasted tables / screenshots reach the model — see
    :func:`build_anthropic_request` for ``images`` (current turn) vs
    ``images_by_student`` (per-turn, replays prior turns)."""
    system_blocks, messages = build_anthropic_request(
        plan, images=images, images_by_student=images_by_student
    )
    client = anthropic.Anthropic(api_key=api_key)
    extractor = StudentAnswerExtractor()
    final_message = None
    enforce = json_mode_enabled()
    stream_kwargs = dict(
        model=model_name, max_tokens=8192, system=system_blocks, messages=messages,
        # Disable extended thinking (mirrors build_tutor_model). Sonnet 5's default
        # is adaptive thinking; left on it streams thinking blocks separately and can
        # burn the whole max_tokens budget before the answer is emitted.
        thinking={"type": "disabled"},
    )
    if enforce:
        # Force a single tutor_reply tool call: the answer arrives as the tool's
        # input (guaranteed-valid JSON), streamed as input_json deltas.
        stream_kwargs.update(anthropic_tool_kwargs())
    with client.messages.stream(**stream_kwargs) as stream:
        if enforce:
            for event in stream:
                if getattr(event, "type", None) == "input_json":
                    visible = extractor.feed(event.partial_json)
                    if visible:
                        yield visible
        else:
            for text in stream.text_stream:
                visible = extractor.feed(text)
                if visible:
                    yield visible
        final_message = stream.get_final_message()

    # Recovery: enforced -> authoritative tool_use.input dict (no repair). Otherwise
    # the accumulated free-text buffer, run through the best-effort normalizer.
    raw = extractor.buffer
    if enforce:
        tool_input = _tool_input_from_message(final_message)
        if tool_input is not None:
            raw = json.dumps(tool_input, ensure_ascii=False)
    normalized = _normalize_tutor_ai_message(AIMessage(content=raw))
    normalized_text = normalized.content if isinstance(normalized.content, str) else str(normalized.content)
    if not extractor.found_answer:
        _, answer = parse_tutor_response(normalized_text)
        if answer:
            yield answer
    yield ("__done__", normalized_text, _anthropic_usage_message(final_message))
