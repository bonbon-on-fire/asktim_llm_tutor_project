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
- :meth:`retrieved_context` — per-turn RAG context to prepend to the student
  message (empty by default; sandbox's RAG mode fills this in).
- :meth:`turn_attachments` — curriculum figures + uploaded images to attach to
  the latest student turn.

No HTTP, no DB, no Flask state — just a shared shape from ``(course,
exercise, tutor, history, new_student_message)`` to a tutor reply.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from tutor.run_tutor import (
    build_tutor_model,
    create_tutor_graph,
    load_system_prompt,
    parse_tutor_response,
)
from tutor.run_tutor import get_tutor_reply as _upstream_get_tutor_reply
from tutor.run_tutor import stream_tutor_reply as _upstream_stream_tutor_reply
from utils.curriculum import (
    SOLUTION_CONTEXT_LABEL,
    exercise_path,
    load_about_asktim,
    read_solution,
)
from utils.figures import build_multimodal_content, discover_figures
from utils.lectures import load_lecture_transcripts


_REPO_ROOT = Path(__file__).resolve().parents[1]
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"


@dataclass
class RetrievedContext:
    """Result of one turn's RAG retrieval.

    ``text`` is the formatted block prepended to the student message; ``records``
    is the JSON-friendly ``[{source, score, chars, text}]`` list persisted into
    transcripts and the DB so callers can see what RAG pulled. Retrieval runs
    once and populates both, so nothing is embedded twice.
    """

    text: str = ""
    records: list[dict] = field(default_factory=list)


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
        """Resolve/normalize the extra per-app kwargs before they're used.

        Called once at the top of :meth:`get_tutor_reply` /
        :meth:`stream_tutor_reply`; the returned dict is threaded through
        every other hook for this call. The base implementation has no extra
        context to resolve.
        """
        return ctx

    def cache_key(self, tutor: str, course: str, exercise: str, **ctx):
        """Key for the graph/stream caches, or ``None`` to skip caching."""
        return (tutor, course, exercise)

    def build_assignment_text(self, course: str, exercise: str, **ctx) -> str:
        """Concatenate about_asktim.txt + course.txt + optional syllabus.txt + optional lecture transcripts + exercise_<NN>.txt.

        Mirrors `internal_testing/run_transcript.py:_build_assignment_text` but omits
        the `Run configuration` block — chats are open-ended, no planned turn
        count. The leading block describes the AskTIM deployment so the tutor
        can coherently answer "what are you?" / "where am I?" questions; it
        lives at `curriculum/about_asktim.txt` and is only read here so
        `tutor/` and the bulk-transcript runners stay unaware of it.
        """
        course_dir = _CURRICULUM_DIR / course
        exercise_text = exercise_path(course, exercise).read_text(encoding="utf-8").strip()

        parts: list[str] = []

        about_text = load_about_asktim()
        if about_text:
            parts.append("About yourself:\n" + about_text)

        course_path = course_dir / "course.txt"
        if course_path.is_file():
            parts.append("Course context:\n" + course_path.read_text(encoding="utf-8").strip())

        syllabus_path = course_dir / "syllabus.txt"
        if syllabus_path.is_file():
            parts.append("Syllabus:\n" + syllabus_path.read_text(encoding="utf-8").strip())

        lectures = load_lecture_transcripts(course)
        if lectures:
            parts.append("Lecture transcripts:\n" + lectures)

        parts.append("Exercise:\n" + exercise_text)

        # Tutor-only correct-answer reference, paired directly to this exercise
        # (never retrieved, never shown to the student). Absent for problems whose
        # solution file doesn't exist yet.
        solution = read_solution(course, exercise, kind="exercise")
        if solution.strip():
            parts.append(SOLUTION_CONTEXT_LABEL + solution.strip())
        return "\n\n".join(parts)

    def build_system_prompt(self, tutor: str, assignment_text: str, **ctx) -> str:
        """Wrap *assignment_text* into the full system prompt for *tutor*."""
        return load_system_prompt(tutor, assignment_override=assignment_text)

    def retrieved_context(self, course: str, query: str, **ctx) -> RetrievedContext:
        """Per-turn RAG retrieval (prompt text + records). Empty by default."""
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

    def _new_student_message(
        self, text: str, images: list | None, retrieved_context: str = ""
    ) -> HumanMessage:
        """Build the new student turn, multimodal when *images* are attached.

        *images* is a list of ``(bytes, mime)`` tuples (or anything
        :func:`utils.figures.build_multimodal_content` accepts). With no images
        this is a plain-text HumanMessage — identical to the text-only path.
        Images are attached only to this (current) turn; prior turns stay
        text-only.

        When ``retrieved_context`` is non-empty (RAG mode), it is prepended as
        a clearly-delimited reference block ahead of the student's actual
        message, so the tutor treats it as background material rather than as
        the student speaking. Only the LLM message is augmented — the
        stored/displayed student message (handled by the route) is unchanged.
        """
        if retrieved_context:
            text = f"{retrieved_context}\n\n---\n\nStudent message:\n{text}"
        return HumanMessage(content=build_multimodal_content(text, images))

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
        system_prompt = self.build_system_prompt(tutor, assignment_text, **ctx)
        graph = create_tutor_graph(system_prompt)
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
        system_prompt = self.build_system_prompt(tutor, assignment_text, **ctx)
        model = build_tutor_model()
        if key is not None:
            self._stream_cache[key] = (model, system_prompt)
        return model, system_prompt

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
        attachments = self.turn_attachments(course, exercise, images, **ctx)
        messages.append(
            self._new_student_message(new_student_message, attachments, rc.text)
        )

        out_messages, reply_text = _upstream_get_tutor_reply(messages, graph=graph)

        reasoning: str | None = None
        if out_messages:
            last = out_messages[-1]
            if isinstance(last, AIMessage):
                raw = last.content if isinstance(last.content, str) else str(last.content)
                reasoning, _ = parse_tutor_response(raw)

        return {"reply": reply_text, "reasoning": reasoning, "retrieved": rc.records}

    def stream_tutor_reply(
        self,
        *,
        course: str,
        exercise: str,
        tutor: str,
        history: list[dict],
        new_student_message: str,
        images: list | None = None,
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
        attachments = self.turn_attachments(course, exercise, images, **ctx)
        messages.append(
            self._new_student_message(new_student_message, attachments, rc.text)
        )

        full_raw: str | None = None
        for item in _upstream_stream_tutor_reply(
            messages, model=model, system_prompt=system_prompt
        ):
            if isinstance(item, tuple) and item and item[0] == "__done__":
                full_raw = item[1]
                break
            if isinstance(item, str) and item:
                yield {"type": "delta", "text": item}

        reasoning: str | None = None
        reply_text = ""
        if full_raw:
            reasoning, answer = parse_tutor_response(full_raw)
            reply_text = answer or ""
        yield {"type": "done", "reply": reply_text, "reasoning": reasoning, "retrieved": rc.records}
