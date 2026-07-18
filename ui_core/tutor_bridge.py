"""Shared base for the per-app tutor bridges (``<app>/services/tutor_bridge.py``).

Both ``main_ui`` and ``sandbox_ui`` talk to ``tutor.run_tutor`` through exactly
one bridge each; the two bridges share the same control flow (build/cache a
graph or model+system_prompt, convert history to LangChain messages, append
the new student turn, call the upstream API, parse the reasoning field) and
differ only at a handful of well-defined points. Those points are exposed here
as overridable hooks:

- :meth:`prepare_ctx` — resolve/normalize the extra per-app kwargs before
  they're threaded through the rest of the call (sandbox resolves
  ``context_mode``; main is a no-op).
- :meth:`cache_key` — the tuple used to key the graph/stream caches. Return
  ``None`` to opt out of caching entirely for this call (sandbox does this
  for one-off custom context).
- :meth:`build_assignment_text` — assemble the assignment/system-prompt body.
- :meth:`build_system_prompt` — wrap the assignment text into a full system
  prompt.
- :meth:`retrieved_context` — per-turn RAG context, always routed to the tutor's
  system/instruction channel, never onto a user turn (empty by default; RAG mode
  fills this in). In the default cache-friendly history mode it rides as its own
  system message interleaved after the turn's student message; in the legacy
  fallback it is folded into the single system message after the cacheable prompt.
- :meth:`turn_attachments` — curriculum figures + uploaded images to attach to
  the latest student turn.

No HTTP, no DB, no Flask state — just a shared shape from ``(course,
exercise, tutor, history, new_student_message)`` to a tutor reply.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from rag.embeddings import EMBEDDING_MODEL
from rag.retrieve import format_context, retrieve_scored_with_usage, to_records
from tutor.cached_history import build_message_plan
from tutor.run_tutor import (
    StudentAnswerExtractor,
    _normalize_tutor_ai_message,
    _require_anthropic_api_key,
    build_tutor_model,
    create_tutor_graph,
    load_system_prompt,
    parse_tutor_response,
    stream_tutor_reply_anthropic_raw,
)
from tutor.run_tutor import get_tutor_reply as _upstream_get_tutor_reply
from tutor.run_tutor import stream_tutor_reply as _upstream_stream_tutor_reply
from utils.curriculum import (
    SOLUTION_CONTEXT_LABEL,
    append_course_tutor_rules,
    exercise_path,
    load_about_asktim,
    practice_path,
    read_pinned_context,
    read_solution,
)
from utils.figures import build_multimodal_content, discover_figures
from utils.lectures import load_lecture_transcripts
from utils.pricing import model_from_message, priced, usage_from_message


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"

# Header prepended to the per-turn RAG grounding, which is folded into the tutor's
# system message. Frames the block as background course material the tutor knows.
RETRIEVED_CONTEXT_HEADER = (
    "Retrieved course material for this turn — background for you only; "
    "cite only the labeled locations that appear below:"
)


@dataclass
class RetrievedContext:
    """Result of one turn's RAG retrieval.

    ``text`` is the formatted block folded into the tutor's system message
    (after the cacheable prompt); ``records`` is the JSON-friendly
    ``[{source, score, chars, text}]`` list persisted into
    transcripts and the DB so callers can see what RAG pulled. Retrieval runs
    once and populates both, so nothing is embedded twice.

    ``embedding_tokens`` is the exact prompt-token count billed for embedding
    the student query this turn (``0`` outside rag mode / when no call is made),
    used to cost-account the embedding call alongside the tutor call.
    """

    text: str = ""
    records: list[dict] = field(default_factory=list)
    embedding_tokens: int = 0


class RagUnavailableError(RuntimeError):
    """Raised when the turn is in ``rag`` mode but retrieval produced no records.

    Covers all three no-RAG triggers uniformly (no index, zero chunks after
    week-scoping, or retrieval raised and was swallowed by ``retrieved_context``).
    The bridge raises this BEFORE any model call; the chat routes convert it to an
    ``event: error`` SSE frame, which the frontend renders as the standard error
    banner with optimistic-bubble rollback. No tutor reply is produced or persisted.
    """


# Context modes (Phase 11). ``rag`` is the default whenever a course has no custom
# context; ``full_context`` bakes course-level material into the prompt; and
# ``exercise_only`` omits it entirely. Override per-deploy with TUTOR_CONTEXT_MODE.
_VALID_CONTEXT_MODES = {"rag", "full_context", "exercise_only"}


def _resolve_context_mode(course: str, has_custom: bool, requested: str | None = None) -> str:
    """Decide how much course material to put in the prompt for this call.

    Precedence: explicit ``requested`` (valid) -> ``TUTOR_CONTEXT_MODE`` env ->
    default ``rag`` whenever there's a course and no custom context, else
    ``full_context``.

    Degrade rule: ``rag`` degrades to ``full_context`` ONLY when ``has_custom`` (a
    tester's pasted context can't be retrieved). A missing index does NOT degrade
    here — the mode stays ``rag`` and the caller fails closed at retrieval time.
    """
    requested = (requested or "").strip().lower()
    env = os.environ.get("TUTOR_CONTEXT_MODE", "").strip().lower()
    if requested in _VALID_CONTEXT_MODES:
        mode = requested
    elif env in _VALID_CONTEXT_MODES:
        mode = env
    else:
        mode = "rag" if (not has_custom and course) else "full_context"
    if mode == "rag" and has_custom:
        mode = "full_context"
    return mode


# Tutor LLM providers. main_ui has no selector and always resolves to the default
# (claude); sandbox_ui lets a tester pick per conversation via the wizard.
_VALID_PROVIDERS = {"gpt", "claude"}
_DEFAULT_PROVIDER = "claude"


def _resolve_provider(requested: str | None) -> str:
    """Tutor provider for this call: ``claude`` (default, Sonnet 5) or ``gpt`` (gpt-5.4)."""
    p = (requested or "").strip().lower()
    return p if p in _VALID_PROVIDERS else _DEFAULT_PROVIDER


_CACHED_HISTORY_FALSEY = {"0", "false", "no", "off"}


def cached_history_enabled() -> bool:
    """Cache-friendly interleaved history is the DEFAULT tutor path.

    Set ``TUTOR_CACHED_HISTORY`` to ``0``/``false``/``no``/``off`` to fall back
    to the legacy single-system path (instant rollback). Any other value — or
    leaving it unset — keeps the cached path.
    """
    return os.environ.get("TUTOR_CACHED_HISTORY", "").strip().lower() not in _CACHED_HISTORY_FALSEY


def _fallback_model(provider: str | None) -> str:
    """Concrete model id for pricing when the response omits one — mirrors build_tutor_model."""
    if _resolve_provider(provider) == "claude":
        return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
    return os.environ.get("OPENAI_MODEL", "gpt-5.4")


def _cost_for_turn(tutor_msg, *, provider: str | None, embedding_tokens: int = 0) -> dict:
    """Estimate the USD cost of one tutor turn from its reported token usage.

    Prices the tutor call (input / output / prompt-cache-read / prompt-cache-write
    tokens) using the *actual* model id reported on the response, plus the RAG
    query-embedding call when it ran (``embedding_tokens > 0``). Returns a
    JSON-serializable breakdown; ``usd`` is the total. Missing usage — a canned or
    fallback reply with no model call (``tutor_msg`` None or without metadata) —
    degrades to zeros rather than crashing (``usage_from_message`` /
    ``model_from_message`` both tolerate ``None``).
    """
    model = model_from_message(tutor_msg, _fallback_model(provider))
    tutor_priced = priced(model, usage_from_message(tutor_msg))
    embedding_priced = (
        priced(EMBEDDING_MODEL, {"input_tokens": int(embedding_tokens)})
        if embedding_tokens
        else None
    )
    total = tutor_priced["usd"] + (embedding_priced["usd"] if embedding_priced else 0.0)
    return {
        "model": model,
        "usd": round(total, 6),
        "tutor": tutor_priced,
        "embedding": embedding_priced,
    }


def _week_for_exercise(exercise) -> int | None:
    """The course week for the current problem, or None if not numeric.

    Exercise / practice numbers share the lecture week number, so a problem
    numbered ``4`` caps retrieval at week 4. Custom / non-numeric exercises have no
    week, so retrieval is left unscoped.
    """
    try:
        return int(str(exercise).strip())
    except (TypeError, ValueError):
        return None


class TutorBridge:
    """Base bridge carrying ``main_ui``'s behavior as the default.

    Subclasses (e.g. sandbox_ui's) override the hook methods below to layer
    RAG / custom-context / include-toggle behavior on top of the same control
    flow. Each instance owns its own graph/stream caches.
    """

    def __init__(self) -> None:
        """Initialize the per-instance graph and streaming caches."""
        self._graph_cache: dict = {}
        # Parallel cache for the streaming path. The non-streaming path drives
        # a compiled LangGraph; the streaming path drives the raw model with
        # the same system prompt. Both are cached per `cache_key(...)` so
        # successive turns reuse the same prompt build.
        self._stream_cache: dict = {}

    # ------------------------------------------------------------------
    # Hooks — override in subclasses. Defaults below are main_ui's behavior.
    # ------------------------------------------------------------------

    def prepare_ctx(self, course: str, **ctx) -> dict:
        """Resolve the per-call context mode and store it in ctx.

        The base bridge has no custom-context feature, so ``has_custom`` is always
        False here; subclasses that add custom context override this.
        """
        ctx["context_mode"] = _resolve_context_mode(
            course, has_custom=False, requested=ctx.get("context_mode")
        )
        return ctx

    def cache_key(self, tutor: str, course: str, exercise: str, **ctx):
        """Key for the graph/stream caches, or ``None`` to skip caching.

        Includes the provider so a gpt and a claude turn for the same
        course/exercise get separate cached (model, system_prompt) entries.
        """
        return (
            tutor,
            course,
            exercise,
            ctx.get("exercise_kind", "exercise"),
            ctx.get("context_mode", "full_context"),
            _resolve_provider(ctx.get("provider")),
        )

    def build_assignment_text(self, course: str, exercise: str, **ctx) -> str:
        """Concatenate about + pinned reference docs (full_context & rag) + lectures (full_context) + exercise + solution key.

        Pinned reference docs live in ``curriculum/<course>/pinned/*.txt`` — the
        course description, syllabus, and any other always-on material (e.g. a
        debugging flow chart). They're folded in for both ``full_context`` and
        ``rag`` and correspondingly excluded from the RAG index (see ``rag.sources``)
        so nothing pinned is also retrieved. Lecture transcripts (large) stay
        ``full_context``-only; in ``rag`` they're reached via retrieval, and
        ``exercise_only`` drops all course material. The exercise and tutor-only
        solution key are always kept.
        """
        mode = ctx.get("context_mode", "full_context")
        kind = ctx.get("exercise_kind", "exercise")
        problem_path = (
            practice_path(course, exercise)
            if kind == "practice"
            else exercise_path(course, exercise)
        )
        exercise_text = problem_path.read_text(encoding="utf-8").strip()

        parts: list[str] = []

        about_text = load_about_asktim()
        if about_text:
            parts.append("About yourself:\n" + about_text)

        # Pinned reference docs (curriculum/<course>/pinned/*.txt) — course description,
        # syllabus, debugging guides, etc. Pinned in full_context AND rag; NOT
        # retrievable (see rag.sources). Each file carries its own title.
        if mode in ("full_context", "rag"):
            pinned = read_pinned_context(course)
            if pinned:
                parts.append(pinned)

        # Lecture transcripts (large): full_context only; retrieved in rag.
        if mode == "full_context":
            lectures = load_lecture_transcripts(course)
            if lectures:
                parts.append("Lecture transcripts:\n" + lectures)

        parts.append("Exercise:\n" + exercise_text)

        # Tutor-only correct-answer reference, paired directly to this exercise
        # (never retrieved, never shown to the student). Absent for problems whose
        # solution file doesn't exist yet.
        solution = read_solution(course, exercise, kind=kind)
        if solution.strip():
            parts.append(SOLUTION_CONTEXT_LABEL + solution.strip())
        return "\n\n".join(parts)

    def build_system_prompt(self, tutor: str, assignment_text: str, course: str = "", **ctx) -> str:
        """Wrap *assignment_text* into the full system prompt for *tutor*.

        When *course* ships a ``curriculum/<course>/tutor_rules.txt``, its
        course-specific rules are appended to the base prompt (see
        ``utils.curriculum.append_course_tutor_rules``); otherwise the base prompt
        is returned unchanged.
        """
        base = load_system_prompt(tutor, assignment_override=assignment_text)
        return append_course_tutor_rules(base, course)

    def retrieved_context(self, course: str, query: str, **ctx) -> RetrievedContext:
        """Per-turn RAG retrieval (prompt text + records); empty outside rag mode.

        In ``rag`` mode, embeds the raw student turn, runs a week-scoped search, and
        returns the formatted block + records. Retrieval failing (e.g. no index or an
        embedding hiccup) returns empty records — the caller fails closed on that.
        """
        if ctx.get("context_mode", "full_context") != "rag":
            return RetrievedContext()
        try:
            scored, embed_tokens = retrieve_scored_with_usage(
                course, query, max_week=_week_for_exercise(ctx.get("exercise"))
            )
            chunks = [c for c, _ in scored]
            return RetrievedContext(
                text=format_context(chunks, course),
                records=to_records(scored),
                embedding_tokens=embed_tokens,
            )
        except Exception:
            return RetrievedContext()

    def turn_attachments(self, course: str, exercise: str, images: list | None, **ctx):
        """Attachments for the latest student turn: curriculum figures + uploads.

        Curriculum figures for ``(course, exercise)`` are filesystem paths
        attached to the latest student turn on *every* call — the per-call
        history is text-only, so the tutor would otherwise lose sight of the
        figure after the first turn. Student-uploaded images (``(bytes,
        mime)`` tuples) ride on the same turn, after the figures. Returns
        ``None`` when there's nothing to attach, so the message stays a
        plain-text HumanMessage.
        """
        figures = discover_figures(course, exercise)
        combined = [*figures, *(images or [])]
        return combined or None

    # ------------------------------------------------------------------
    # Shared machinery — subclasses should not need to reimplement these.
    # ------------------------------------------------------------------

    def _history_to_langchain(self, history: list[dict]) -> list:
        """Convert [{role, content}, ...] dicts to LangChain BaseMessage instances."""
        messages: list = []
        for entry in history:
            role = entry["role"]
            content = entry["content"]
            if role == "student":
                messages.append(HumanMessage(content=content))
            elif role == "tutor":
                messages.append(AIMessage(content=content))
            else:
                raise ValueError(f"Unknown role: {role!r} (expected 'student' or 'tutor')")
        return messages

    def _new_student_message(self, text: str, images: list | None) -> HumanMessage:
        """Build the new student turn, multimodal when *images* are attached.

        *images* is a list of ``(bytes, mime)`` tuples (or anything
        :func:`utils.figures.build_multimodal_content` accepts). With no images
        this is a plain-text HumanMessage — identical to the text-only path.
        Images are attached only to this (current) turn; prior turns stay
        text-only.

        The student's text is used verbatim: any per-turn RAG grounding is folded
        into the system message (see :meth:`_retrieved_context_block`), never glued
        onto the student's words, so the student turn the model sees stays pristine.
        """
        return HumanMessage(content=build_multimodal_content(text, images))

    def _retrieved_context_block(self, retrieved_context: str) -> str:
        """Frame this turn's RAG grounding for the system message.

        Returns the header + retrieved block as a string. It's folded into the
        tutor's system message (after the cacheable prompt) rather than sent on
        a user turn, so the student's words stay clean and the material reads as
        background course knowledge in the instruction channel. Empty in →
        empty out. Only the LLM sees this; the stored/displayed student message
        is unchanged.
        """
        if not retrieved_context:
            return ""
        return f"{RETRIEVED_CONTEXT_HEADER}\n\n{retrieved_context}"

    def _plan_to_langchain(self, plan):
        """Convert a (role, content) message plan into langchain messages
        (GPT cached path — langchain accepts interleaved system messages)."""
        out = []
        for role, content in plan:
            if role in ("system_static", "rag"):
                out.append(SystemMessage(content=content))
            elif role == "student":
                out.append(HumanMessage(content=content))
            else:  # tutor
                out.append(AIMessage(content=content))
        return out

    def _get_or_build_graph(self, tutor: str, course: str, exercise: str, **ctx):
        """Return the cached compiled tutor graph for this call, building it on a miss.

        Skips the cache entirely when :meth:`cache_key` returns ``None``.
        """
        key = self.cache_key(tutor, course, exercise, **ctx)
        if key is not None:
            cached = self._graph_cache.get(key)
            if cached is not None:
                return cached
        assignment_text = self.build_assignment_text(course, exercise, **ctx)
        system_prompt = self.build_system_prompt(tutor, assignment_text, course=course, **ctx)
        # Tutor provider is per-call: main_ui never passes one (-> claude/Sonnet 5),
        # sandbox_ui threads the tester's wizard choice through ctx.
        graph = create_tutor_graph(system_prompt, provider=_resolve_provider(ctx.get("provider")))
        if key is not None:
            self._graph_cache[key] = graph
        return graph

    def _get_or_build_stream_context(
        self, tutor: str, course: str, exercise: str, **ctx
    ) -> tuple[object, str]:
        """Return ``(model, system_prompt)`` for the streaming path."""
        key = self.cache_key(tutor, course, exercise, **ctx)
        if key is not None:
            cached = self._stream_cache.get(key)
            if cached is not None:
                return cached
        assignment_text = self.build_assignment_text(course, exercise, **ctx)
        system_prompt = self.build_system_prompt(tutor, assignment_text, course=course, **ctx)
        # Per-call provider for the streaming path too — see _get_or_build_graph.
        model = build_tutor_model(provider=_resolve_provider(ctx.get("provider")))
        if key is not None:
            self._stream_cache[key] = (model, system_prompt)
        return model, system_prompt

    def _enforce_rag_available(self, ctx: dict, rc: RetrievedContext) -> None:
        """Fail closed: in rag mode, refuse the turn when retrieval produced nothing.

        Covers no-index, zero-chunks, and retrieval-threw (all collapse to empty
        records). Raised before any model call so no tutor reply is produced,
        streamed, or persisted; the chat route turns it into an ``event: error`` frame.
        """
        if ctx.get("context_mode") == "rag" and not rc.records:
            raise RagUnavailableError(
                "RAG is unavailable for this turn (no retrievable course material)."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_tutor_reply(
        self,
        *,
        course: str,
        exercise: str,
        tutor: str,
        history: list[dict],
        new_student_message: str,
        images: list | None = None,
        **ctx,
    ) -> dict:
        """Return one tutor reply for the given conversation state.

        Args:
            course: course slug under ``curriculum/`` (e.g. ``cities_and_climate_change``)
            exercise: exercise number, non-padded (e.g. ``"4"``)
            tutor: tutor prompt stem (e.g. ``"tutor_05"``)
            history: prior conversation as ``[{"role": "student"|"tutor", "content": str}, ...]``
            new_student_message: the latest student turn to respond to
            images: optional ``(bytes, mime)`` tuples attached to this student turn
            ctx: app-specific extra context (see subclass hooks)

        Returns:
            ``{"reply": str, "reasoning": str | None}`` — reasoning is the
            tutor's hidden ``pedagogical-reasoning`` field; ``None`` if parsing
            the tutor's JSON failed.
        """
        ctx = self.prepare_ctx(course, **ctx)
        graph = self._get_or_build_graph(tutor, course, exercise, **ctx)
        messages = self._history_to_langchain(history)
        rc = self.retrieved_context(course, new_student_message, exercise=exercise, **ctx)
        self._enforce_rag_available(ctx, rc)
        attachments = self.turn_attachments(course, exercise, images, **ctx)
        messages.append(self._new_student_message(new_student_message, attachments))

        out_messages, reply_text = _upstream_get_tutor_reply(
            messages, graph=graph, retrieved_context=self._retrieved_context_block(rc.text)
        )

        reasoning: str | None = None
        last_msg = out_messages[-1] if out_messages else None
        if isinstance(last_msg, AIMessage):
            raw = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)
            reasoning, _ = parse_tutor_response(raw)

        cost = _cost_for_turn(
            last_msg, provider=ctx.get("provider"), embedding_tokens=rc.embedding_tokens
        )
        return {
            "reply": reply_text,
            "reasoning": reasoning,
            "retrieved": rc.records,
            "cost": cost,
        }

    def stream_tutor_reply(
        self,
        *,
        course: str,
        exercise: str,
        tutor: str,
        history: list[dict],
        new_student_message: str,
        images: list | None = None,
        history_mode: str = "legacy",
        cached_history: list[dict] | None = None,
        **ctx,
    ):
        """Stream a tutor reply as a sequence of event dicts.

        Yields:
            ``{"type": "delta", "text": "..."}`` for each batch of visible
            student-facing characters, then exactly one terminal event:
            ``{"type": "done", "reply": "...", "reasoning": "..." | None}``.

        *images* (``(bytes, mime)`` tuples) attach to this student turn as
        multimodal content. Routes are responsible for re-shaping these into
        SSE frames.
        """
        ctx = self.prepare_ctx(course, **ctx)
        model, system_prompt = self._get_or_build_stream_context(
            tutor, course, exercise, **ctx
        )
        messages = self._history_to_langchain(history)
        rc = self.retrieved_context(course, new_student_message, exercise=exercise, **ctx)
        self._enforce_rag_available(ctx, rc)

        if history_mode == "cached":
            provider = _resolve_provider(ctx.get("provider"))
            plan = build_message_plan(
                static_system=system_prompt,
                prior_turns=cached_history or [],
                current_student=new_student_message,
                current_rag=self._retrieved_context_block(rc.text),
            )
            full_raw = None
            full_msg = None  # usage-bearing message for cost accounting
            if provider == "claude":
                for item in stream_tutor_reply_anthropic_raw(
                    plan,
                    model_name=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5"),
                    api_key=_require_anthropic_api_key(),
                ):
                    if isinstance(item, tuple) and item and item[0] == "__done__":
                        full_raw = item[1]
                        full_msg = item[2] if len(item) > 2 else None
                        break
                    if isinstance(item, str) and item:
                        yield {"type": "delta", "text": item}
            else:  # gpt via langchain (accepts interleaved system messages)
                lc_messages = self._plan_to_langchain(plan)
                extractor = StudentAnswerExtractor()
                full_chunk = None
                for chunk in model.stream(lc_messages):
                    full_chunk = chunk if full_chunk is None else full_chunk + chunk
                    piece = chunk.content if hasattr(chunk, "content") else str(chunk)
                    if not isinstance(piece, str):
                        piece = str(piece)
                    visible = extractor.feed(piece)
                    if visible:
                        yield {"type": "delta", "text": visible}
                full_raw = _normalize_tutor_ai_message(AIMessage(content=extractor.buffer)).content
                full_msg = full_chunk  # carries usage_metadata when stream_usage=True
            reasoning, answer = (None, "")
            if full_raw:
                reasoning, answer = parse_tutor_response(full_raw)
            cost = _cost_for_turn(
                full_msg, provider=provider, embedding_tokens=rc.embedding_tokens
            )
            yield {
                "type": "done",
                "reply": answer or "",
                "reasoning": reasoning,
                "retrieved": rc.records,
                "cost": cost,
            }
            return

        attachments = self.turn_attachments(course, exercise, images, **ctx)
        messages.append(self._new_student_message(new_student_message, attachments))

        full_raw: str | None = None
        full_msg = None
        for item in _upstream_stream_tutor_reply(
            messages,
            model=model,
            system_prompt=system_prompt,
            retrieved_context=self._retrieved_context_block(rc.text),
        ):
            if isinstance(item, tuple) and item and item[0] == "__done__":
                full_raw = item[1]
                # Third element (the usage-bearing AIMessage) is optional for
                # backward-compatible callers/fakes that yield only a 2-tuple.
                full_msg = item[2] if len(item) > 2 else None
                break
            if isinstance(item, str) and item:
                yield {"type": "delta", "text": item}

        reasoning: str | None = None
        reply_text = ""
        if full_raw:
            reasoning, answer = parse_tutor_response(full_raw)
            reply_text = answer or ""
        cost = _cost_for_turn(
            full_msg, provider=ctx.get("provider"), embedding_tokens=rc.embedding_tokens
        )
        yield {
            "type": "done",
            "reply": reply_text,
            "reasoning": reasoning,
            "retrieved": rc.records,
            "cost": cost,
        }
