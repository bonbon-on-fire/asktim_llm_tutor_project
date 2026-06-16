"""Bridge from test_ui to the existing tutor.run_tutor pipeline.

The one place in `test_ui` that talks to `tutor.run_tutor`. Routes call
`get_tutor_reply(...)` here; they never import the upstream tutor API
directly. If the underlying tutor API changes shape later, only this module
needs updating.

No HTTP, no DB, no Flask state — just a thin function from
``(course, exercise, tutor, history, new_student_message)`` to a tutor reply.
"""

from __future__ import annotations

import re
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
from utils.curriculum import exercise_path
from utils.figures import build_multimodal_content


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_ABOUT_ASKTIM_PATH = Path(__file__).resolve().parents[1] / "about_asktim.txt"


_graph_cache: dict[tuple[str, str, str, bool], object] = {}
# Parallel cache for the streaming path. The non-streaming path drives a
# compiled LangGraph; the streaming path drives the raw model with the same
# system prompt. We cache both per (tutor, course, exercise, include_syllabus)
# so successive turns reuse the same prompt build.
_stream_cache: dict[tuple[str, str, str, bool], tuple[object, str]] = {}


def build_assignment_text(
    course: str,
    exercise: str,
    *,
    include_syllabus: bool = True,
    course_text: str | None = None,
    exercise_text: str | None = None,
    syllabus_text: str | None = None,
) -> str:
    """Concatenate about_asktim.txt + course.txt + optional syllabus.txt + exercise_<NN>.txt.

    Mirrors `internal_ui/run_ui_raw.py:_build_assignment_text` but omits the
    `Run configuration` block — test_ui chats are open-ended, no planned
    turn count. The leading block describes the AskTIM deployment so the
    tutor can coherently answer "what are you?" / "where am I?" questions;
    it lives at `test_ui/about_asktim.txt` and is only read here so
    `tutor/` and the bulk-transcript runners stay unaware of it.

    ``include_syllabus`` is a test_ui addition: when False, the course
    ``syllabus.txt`` block is dropped so testers can compare tutor behaviour
    with and without the syllabus in context.

    The ``*_text`` overrides carry one-off custom context typed in the
    "Create context" wizard. When a given override is not ``None`` it is used
    verbatim (and the matching on-disk file is NOT read); an empty/whitespace
    override simply omits that block. This lets testers mix custom and
    built-in fields freely.
    """
    course_dir = _CURRICULUM_DIR / course if course else None

    parts: list[str] = []

    if _ABOUT_ASKTIM_PATH.is_file():
        about_text = _ABOUT_ASKTIM_PATH.read_text(encoding="utf-8").strip()
        if about_text:
            parts.append("About yourself:\n" + about_text)

    # Course context — custom text wins; otherwise read course.txt.
    if course_text is not None:
        if course_text.strip():
            parts.append("Course context:\n" + course_text.strip())
    elif course_dir is not None:
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
    course_text: str | None,
    exercise_text: str | None,
    syllabus_text: str | None,
    custom_tutor_prompt: str | None,
) -> str:
    assignment_text = build_assignment_text(
        course,
        exercise,
        include_syllabus=include_syllabus,
        course_text=course_text,
        exercise_text=exercise_text,
        syllabus_text=syllabus_text,
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
    course_text: str | None = None,
    exercise_text: str | None = None,
    syllabus_text: str | None = None,
    custom_tutor_prompt: str | None = None,
):
    custom = _has_custom(course_text, exercise_text, syllabus_text, custom_tutor_prompt)
    if not custom:
        cached = _graph_cache.get((tutor, course, exercise, include_syllabus))
        if cached is not None:
            return cached
    system_prompt = _resolve_system_prompt(
        tutor,
        course,
        exercise,
        include_syllabus,
        course_text=course_text,
        exercise_text=exercise_text,
        syllabus_text=syllabus_text,
        custom_tutor_prompt=custom_tutor_prompt,
    )
    graph = create_tutor_graph(system_prompt)
    if not custom:
        # Only cache reusable built-in builds — custom context is one-off.
        _graph_cache[(tutor, course, exercise, include_syllabus)] = graph
    return graph


def _get_or_build_stream_context(
    tutor: str,
    course: str,
    exercise: str,
    include_syllabus: bool,
    *,
    course_text: str | None = None,
    exercise_text: str | None = None,
    syllabus_text: str | None = None,
    custom_tutor_prompt: str | None = None,
) -> tuple[object, str]:
    """Return ``(model, system_prompt)`` for the streaming path."""
    custom = _has_custom(course_text, exercise_text, syllabus_text, custom_tutor_prompt)
    if not custom:
        cached = _stream_cache.get((tutor, course, exercise, include_syllabus))
        if cached is not None:
            return cached
    system_prompt = _resolve_system_prompt(
        tutor,
        course,
        exercise,
        include_syllabus,
        course_text=course_text,
        exercise_text=exercise_text,
        syllabus_text=syllabus_text,
        custom_tutor_prompt=custom_tutor_prompt,
    )
    model = build_tutor_model()
    if not custom:
        _stream_cache[(tutor, course, exercise, include_syllabus)] = (model, system_prompt)
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


def _new_student_message(text: str, images: list | None) -> HumanMessage:
    """Build the new student turn, multimodal when *images* are attached.

    *images* is a list of ``(bytes, mime)`` tuples. With none, this is a plain
    text HumanMessage. Images attach only to this turn; prior turns stay text.
    """
    return HumanMessage(content=build_multimodal_content(text, images))


def get_tutor_reply(
    *,
    course: str,
    exercise: str,
    tutor: str,
    history: list[dict],
    new_student_message: str,
    images: list | None = None,
    include_syllabus: bool = True,
    course_text: str | None = None,
    exercise_text: str | None = None,
    syllabus_text: str | None = None,
    custom_tutor_prompt: str | None = None,
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
    graph = _get_or_build_graph(
        tutor,
        course,
        exercise,
        include_syllabus,
        course_text=course_text,
        exercise_text=exercise_text,
        syllabus_text=syllabus_text,
        custom_tutor_prompt=custom_tutor_prompt,
    )
    messages = _history_to_langchain(history)
    messages.append(_new_student_message(new_student_message, images))

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
    include_syllabus: bool = True,
    course_text: str | None = None,
    exercise_text: str | None = None,
    syllabus_text: str | None = None,
    custom_tutor_prompt: str | None = None,
):
    """Stream a tutor reply as a sequence of event dicts.

    Yields:
        ``{"type": "delta", "text": "..."}`` for each batch of visible
        student-facing characters, then exactly one terminal event:
        ``{"type": "done", "reply": "...", "reasoning": "..." | None}``.

    Routes are responsible for re-shaping these into SSE frames.
    """
    model, system_prompt = _get_or_build_stream_context(
        tutor,
        course,
        exercise,
        include_syllabus,
        course_text=course_text,
        exercise_text=exercise_text,
        syllabus_text=syllabus_text,
        custom_tutor_prompt=custom_tutor_prompt,
    )
    messages = _history_to_langchain(history)
    messages.append(_new_student_message(new_student_message, images))

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
