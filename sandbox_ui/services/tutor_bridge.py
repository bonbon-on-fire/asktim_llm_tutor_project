"""Bridge from sandbox_ui to the existing tutor.run_tutor pipeline.

The one place in `sandbox_ui` that talks to `tutor.run_tutor`. Routes call
`get_tutor_reply(...)` here; they never import the upstream tutor API
directly. If the underlying tutor API changes shape later, only this module
needs updating.

No HTTP, no DB, no Flask state — just a thin function from
``(course, exercise, tutor, history, new_student_message)`` to a tutor reply.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from rag.retrieve import format_context
from rag.retrieve import has_index as rag_has_index
from rag.retrieve import retrieve as rag_retrieve
from tutor.run_tutor import (
    build_tutor_model,
    create_tutor_graph,
    load_system_prompt,
    parse_tutor_response,
)
from tutor.run_tutor import get_tutor_reply as _upstream_get_tutor_reply
from tutor.run_tutor import stream_tutor_reply as _upstream_stream_tutor_reply
from utils.curriculum import exercise_path
from utils.figures import build_multimodal_content, discover_figures


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_ABOUT_ASKTIM_PATH = Path(__file__).resolve().parents[1] / "about_asktim.txt"

# Context modes (Phase 11). Override per-deploy with the TUTOR_CONTEXT_MODE env
# var; otherwise default to "rag" when a course has a built index, else fall
# back to the historical "full_context" behavior.
_VALID_CONTEXT_MODES = {"rag", "full_context", "exercise_only"}


_graph_cache: dict[tuple[str, str, str, bool, bool, str], object] = {}
# Parallel cache for the streaming path. The non-streaming path drives a
# compiled LangGraph; the streaming path drives the raw model with the same
# system prompt. We cache both per (tutor, course, exercise, include_course,
# include_syllabus, context_mode) so successive turns reuse the same prompt build.
_stream_cache: dict[tuple[str, str, str, bool, bool, str], tuple[object, str]] = {}


def _resolve_context_mode(
    course: str, has_custom: bool, requested: str | None = None
) -> str:
    """Decide how much course material to put in the prompt for this call.

    Precedence:
    - ``requested`` (the per-conversation choice from the Sandbox RAG toggle)
      wins when valid — it's the most specific signal.
    - else ``TUTOR_CONTEXT_MODE`` env (deploy-wide override).
    - else default to ``rag`` when the course has a built index and there's no
      one-off custom context, else ``full_context`` (historical behavior).

    ``rag`` degrades to ``full_context`` if there's no index or custom context is
    in play (a tester's typed-in course/exercise can't be retrieved).
    """
    requested = (requested or "").strip().lower()
    env = os.environ.get("TUTOR_CONTEXT_MODE", "").strip().lower()
    if requested in _VALID_CONTEXT_MODES:
        mode = requested
    elif env in _VALID_CONTEXT_MODES:
        mode = env
    else:
        mode = "rag" if (not has_custom and course and rag_has_index(course)) else "full_context"
    if mode == "rag" and (has_custom or not (course and rag_has_index(course))):
        mode = "full_context"
    return mode


def build_assignment_text(
    course: str,
    exercise: str,
    *,
    include_course: bool = True,
    include_syllabus: bool = True,
    course_text: str | None = None,
    exercise_text: str | None = None,
    syllabus_text: str | None = None,
    context_mode: str = "full_context",
) -> str:
    """Concatenate about_asktim.txt + course.txt + optional syllabus.txt + exercise_<NN>.txt.

    ``context_mode`` controls how much course-level material is baked into the
    prompt. In ``full_context`` (default) the course description and syllabus are
    included as today. In ``rag`` / ``exercise_only`` they are dropped — course,
    syllabus, and lectures are reached via retrieval (``rag``) or omitted
    (``exercise_only``) — leaving only the about-block and the exercise, which is
    the one thing always kept in context verbatim.

    Mirrors `internal_ui/run_ui_raw.py:_build_assignment_text` but omits the
    `Run configuration` block — sandbox_ui chats are open-ended, no planned
    turn count. The leading block describes the AskTIM deployment so the
    tutor can coherently answer "what are you?" / "where am I?" questions;
    it lives at `sandbox_ui/about_asktim.txt` and is only read here so
    `tutor/` and the bulk-transcript runners stay unaware of it.

    ``include_course`` / ``include_syllabus`` are sandbox_ui additions: when
    False, the course ``course.txt`` description / ``syllabus.txt`` block is
    dropped so testers can compare tutor behaviour with and without that
    material in context. Both gate only the built-in on-disk files; a custom
    ``course_text`` / ``syllabus_text`` override is always included verbatim.

    The ``*_text`` overrides carry one-off custom context typed in the
    "Create context" wizard. When a given override is not ``None`` it is used
    verbatim (and the matching on-disk file is NOT read); an empty/whitespace
    override simply omits that block. This lets testers mix custom and
    built-in fields freely.
    """
    course_dir = _CURRICULUM_DIR / course if course else None
    # Course + syllabus go in the prompt only in full_context; in rag /
    # exercise_only they're retrieved or omitted (the exercise still always goes in).
    include_course_material = context_mode == "full_context"

    parts: list[str] = []

    if _ABOUT_ASKTIM_PATH.is_file():
        about_text = _ABOUT_ASKTIM_PATH.read_text(encoding="utf-8").strip()
        if about_text:
            parts.append("About yourself:\n" + about_text)

    # Course context — custom text wins; otherwise the include_course toggle
    # gates the built-in course.txt (mirrors the syllabus handling below).
    if include_course_material:
        if course_text is not None:
            if course_text.strip():
                parts.append("Course context:\n" + course_text.strip())
        elif include_course and course_dir is not None:
            course_path = course_dir / "course.txt"
            if course_path.is_file():
                parts.append(
                    "Course context:\n" + course_path.read_text(encoding="utf-8").strip()
                )

        # Syllabus — custom text wins; otherwise the built-in toggle gates the file.
        if syllabus_text is not None:
            if syllabus_text.strip():
                parts.append("Syllabus:\n" + syllabus_text.strip())
        elif include_syllabus and course_dir is not None:
            syllabus_path = course_dir / "syllabus.txt"
            if syllabus_path.is_file():
                parts.append(
                    "Syllabus:\n" + syllabus_path.read_text(encoding="utf-8").strip()
                )

    # Exercise — custom text wins; otherwise read exercise_<NN>.txt.
    if exercise_text is not None:
        resolved_exercise = exercise_text.strip()
    else:
        resolved_exercise = exercise_path(course, exercise).read_text(encoding="utf-8").strip()
    parts.append("Exercise:\n" + resolved_exercise)

    return "\n\n".join(parts)


def _render_custom_tutor_prompt(prompt_text: str, assignment_override: str) -> str:
    """Render a tester-supplied tutor prompt, injecting the assignment.

    Mirrors `tutor.load_system_prompt`'s `<Assignment>` substitution, but for
    raw prompt text instead of a file. If the custom prompt has no
    `<Assignment>` block, the assignment is appended so the tutor still sees
    the exercise.
    """
    if "<Assignment>" in prompt_text and "</Assignment>" in prompt_text:
        rendered = re.sub(
            r"<Assignment>.*?</Assignment>",
            f"<Assignment>\n{assignment_override.strip()}\n</Assignment>",
            prompt_text,
            flags=re.DOTALL,
        )
    else:
        rendered = (
            prompt_text.rstrip()
            + f"\n\n<Assignment>\n{assignment_override.strip()}\n</Assignment>"
        )
    return rendered.strip()


def _has_custom(
    course_text: str | None,
    exercise_text: str | None,
    syllabus_text: str | None,
    custom_tutor_prompt: str | None,
) -> bool:
    return any(
        v is not None
        for v in (course_text, exercise_text, syllabus_text, custom_tutor_prompt)
    )


def _resolve_system_prompt(
    tutor: str,
    course: str,
    exercise: str,
    include_syllabus: bool,
    *,
    include_course: bool = True,
    course_text: str | None,
    exercise_text: str | None,
    syllabus_text: str | None,
    custom_tutor_prompt: str | None,
    context_mode: str = "full_context",
) -> str:
    assignment_text = build_assignment_text(
        course,
        exercise,
        include_course=include_course,
        include_syllabus=include_syllabus,
        course_text=course_text,
        exercise_text=exercise_text,
        syllabus_text=syllabus_text,
        context_mode=context_mode,
    )
    if custom_tutor_prompt is not None:
        return _render_custom_tutor_prompt(custom_tutor_prompt, assignment_text)
    return load_system_prompt(tutor, assignment_override=assignment_text)


def _get_or_build_graph(
    tutor: str,
    course: str,
    exercise: str,
    include_syllabus: bool,
    *,
    include_course: bool = True,
    course_text: str | None = None,
    exercise_text: str | None = None,
    syllabus_text: str | None = None,
    custom_tutor_prompt: str | None = None,
    context_mode: str = "full_context",
):
    custom = _has_custom(course_text, exercise_text, syllabus_text, custom_tutor_prompt)
    key = (tutor, course, exercise, include_course, include_syllabus, context_mode)
    if not custom:
        cached = _graph_cache.get(key)
        if cached is not None:
            return cached
    system_prompt = _resolve_system_prompt(
        tutor,
        course,
        exercise,
        include_syllabus,
        include_course=include_course,
        course_text=course_text,
        exercise_text=exercise_text,
        syllabus_text=syllabus_text,
        custom_tutor_prompt=custom_tutor_prompt,
        context_mode=context_mode,
    )
    graph = create_tutor_graph(system_prompt)
    if not custom:
        # Only cache reusable built-in builds — custom context is one-off.
        _graph_cache[key] = graph
    return graph


def _get_or_build_stream_context(
    tutor: str,
    course: str,
    exercise: str,
    include_syllabus: bool,
    *,
    include_course: bool = True,
    course_text: str | None = None,
    exercise_text: str | None = None,
    syllabus_text: str | None = None,
    custom_tutor_prompt: str | None = None,
    context_mode: str = "full_context",
) -> tuple[object, str]:
    """Return ``(model, system_prompt)`` for the streaming path."""
    custom = _has_custom(course_text, exercise_text, syllabus_text, custom_tutor_prompt)
    key = (tutor, course, exercise, include_course, include_syllabus, context_mode)
    if not custom:
        cached = _stream_cache.get(key)
        if cached is not None:
            return cached
    system_prompt = _resolve_system_prompt(
        tutor,
        course,
        exercise,
        include_syllabus,
        include_course=include_course,
        course_text=course_text,
        exercise_text=exercise_text,
        syllabus_text=syllabus_text,
        custom_tutor_prompt=custom_tutor_prompt,
        context_mode=context_mode,
    )
    model = build_tutor_model()
    if not custom:
        _stream_cache[key] = (model, system_prompt)
    return model, system_prompt


def _history_to_langchain(history: list[dict]) -> list:
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
    text: str, images: list | None, retrieved_context: str = ""
) -> HumanMessage:
    """Build the new student turn, multimodal when *images* are attached.

    *images* is a list of ``(bytes, mime)`` tuples. With none, this is a plain
    text HumanMessage. Images attach only to this turn; prior turns stay text.

    When ``retrieved_context`` is provided (RAG mode), it is prepended as a
    clearly-delimited reference block ahead of the student's actual message, so
    the tutor treats it as background material rather than as the student
    speaking. Only the LLM message is augmented — the stored/displayed student
    message (handled by the route) is unchanged.
    """
    if retrieved_context:
        text = f"{retrieved_context}\n\n---\n\nStudent message:\n{text}"
    return HumanMessage(content=build_multimodal_content(text, images))


def _retrieved_context(course: str, mode: str, query: str) -> str:
    """Retrieve and format course-material chunks for this turn (RAG mode only)."""
    if mode != "rag":
        return ""
    try:
        return format_context(rag_retrieve(course, query))
    except Exception:
        # Retrieval failing (e.g. embedding API hiccup) must not break the chat;
        # degrade to no retrieved context for this turn.
        return ""


def _turn_attachments(
    course: str,
    exercise: str,
    images: list | None,
    *,
    course_text: str | None,
    exercise_text: str | None,
) -> list | None:
    """Attachments for the latest student turn: curriculum figures + uploads.

    Curriculum figures attach only when the course *and* exercise are built-ins
    (no custom override) — a tester's typed-in custom exercise has no figures
    folder on disk. When they apply, figures are filesystem paths attached on
    every call (the per-call history is text-only, so the tutor would otherwise
    lose the figure after the first turn). Student uploads (``(bytes, mime)``
    tuples) ride on the same turn, after the figures. Returns ``None`` when
    there's nothing to attach, keeping the message a plain-text HumanMessage.
    """
    figures: list = []
    if course and course_text is None and exercise_text is None:
        figures = discover_figures(course, exercise)
    combined = [*figures, *(images or [])]
    return combined or None


def get_tutor_reply(
    *,
    course: str,
    exercise: str,
    tutor: str,
    history: list[dict],
    new_student_message: str,
    images: list | None = None,
    include_course: bool = True,
    include_syllabus: bool = True,
    course_text: str | None = None,
    exercise_text: str | None = None,
    syllabus_text: str | None = None,
    custom_tutor_prompt: str | None = None,
    context_mode: str | None = None,
) -> dict:
    """Return one tutor reply for the given conversation state.

    Args:
        course: course slug under ``curriculum/`` (e.g. ``cities_and_climate_change``)
        exercise: zero-padded 2-digit exercise number (e.g. ``"04"``)
        tutor: tutor prompt stem (e.g. ``"tutor_05"``)
        history: prior conversation as ``[{"role": "student"|"tutor", "content": str}, ...]``
        new_student_message: the latest student turn to respond to
        include_syllabus: whether to fold the course syllabus into context
        course_text / exercise_text / syllabus_text / custom_tutor_prompt:
            one-off custom context overrides (see ``build_assignment_text``)

    Returns:
        ``{"reply": str, "reasoning": str | None}`` — reasoning is the
        tutor's hidden ``pedagogical-reasoning`` field; ``None`` if parsing
        the tutor's JSON failed.
    """
    has_custom = _has_custom(course_text, exercise_text, syllabus_text, custom_tutor_prompt)
    context_mode = _resolve_context_mode(course, has_custom, requested=context_mode)
    graph = _get_or_build_graph(
        tutor,
        course,
        exercise,
        include_syllabus,
        include_course=include_course,
        course_text=course_text,
        exercise_text=exercise_text,
        syllabus_text=syllabus_text,
        custom_tutor_prompt=custom_tutor_prompt,
        context_mode=context_mode,
    )
    messages = _history_to_langchain(history)
    messages.append(
        _new_student_message(
            new_student_message,
            _turn_attachments(
                course,
                exercise,
                images,
                course_text=course_text,
                exercise_text=exercise_text,
            ),
            _retrieved_context(course, context_mode, new_student_message),
        )
    )

    out_messages, reply_text = _upstream_get_tutor_reply(messages, graph=graph)

    reasoning: str | None = None
    if out_messages:
        last = out_messages[-1]
        if isinstance(last, AIMessage):
            raw = last.content if isinstance(last.content, str) else str(last.content)
            reasoning, _ = parse_tutor_response(raw)

    return {"reply": reply_text, "reasoning": reasoning}


def stream_tutor_reply(
    *,
    course: str,
    exercise: str,
    tutor: str,
    history: list[dict],
    new_student_message: str,
    images: list | None = None,
    include_course: bool = True,
    include_syllabus: bool = True,
    course_text: str | None = None,
    exercise_text: str | None = None,
    syllabus_text: str | None = None,
    custom_tutor_prompt: str | None = None,
    context_mode: str | None = None,
):
    """Stream a tutor reply as a sequence of event dicts.

    Yields:
        ``{"type": "delta", "text": "..."}`` for each batch of visible
        student-facing characters, then exactly one terminal event:
        ``{"type": "done", "reply": "...", "reasoning": "..." | None}``.

    Routes are responsible for re-shaping these into SSE frames.
    """
    has_custom = _has_custom(course_text, exercise_text, syllabus_text, custom_tutor_prompt)
    context_mode = _resolve_context_mode(course, has_custom, requested=context_mode)
    model, system_prompt = _get_or_build_stream_context(
        tutor,
        course,
        exercise,
        include_syllabus,
        include_course=include_course,
        course_text=course_text,
        exercise_text=exercise_text,
        syllabus_text=syllabus_text,
        custom_tutor_prompt=custom_tutor_prompt,
        context_mode=context_mode,
    )
    messages = _history_to_langchain(history)
    messages.append(
        _new_student_message(
            new_student_message,
            _turn_attachments(
                course,
                exercise,
                images,
                course_text=course_text,
                exercise_text=exercise_text,
            ),
            _retrieved_context(course, context_mode, new_student_message),
        )
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
    yield {"type": "done", "reply": reply_text, "reasoning": reasoning}
