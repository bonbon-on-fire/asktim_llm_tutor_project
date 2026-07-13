"""Bridge from sandbox_ui to the existing tutor.run_tutor pipeline.

The one place in `sandbox_ui` that talks to `tutor.run_tutor`. Routes call
`get_tutor_reply(...)` here; they never import the upstream tutor API
directly. If the underlying tutor API changes shape later, only this module
needs updating.

No HTTP, no DB, no Flask state — just a thin function from
``(course, exercise, tutor, history, new_student_message)`` to a tutor reply.

The shared control flow (build/cache a graph or model+system_prompt, convert
history, append the new turn, call upstream, parse reasoning) lives in
:class:`ui_core.tutor_bridge.TutorBridge`. ``SandboxTutorBridge`` below
overrides that base's ``cache_key`` / ``build_assignment_text`` hooks to add
sandbox_ui's include-toggle behavior; the module-level functions at the
bottom are a thin wrapper around one shared instance, preserving the exact
public names and call signatures `sandbox_ui/routes/*` import.
"""

from __future__ import annotations

from pathlib import Path

from ui_core.tutor_bridge import TutorBridge
from utils.curriculum import (
    SOLUTION_CONTEXT_LABEL,
    exercise_path,
    load_about_asktim,
    practice_path,
    read_solution,
)
from utils.lectures import load_lecture_transcripts


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"


def build_assignment_text(
    course: str,
    exercise: str,
    *,
    exercise_kind: str = "exercise",
    include_course: bool = True,
    include_syllabus: bool = True,
    include_lectures: bool = True,
    context_mode: str = "full_context",
) -> str:
    """Concatenate about_asktim.txt + course.txt + optional syllabus.txt + optional lectures + exercise_<NN>.txt.

    ``context_mode`` controls how much course-level material is baked into the
    prompt. In ``full_context`` (default) the course description and syllabus are
    included as today. In ``rag`` / ``exercise_only`` they are dropped — course,
    syllabus, and lectures are reached via retrieval (``rag``) or omitted
    (``exercise_only``) — leaving only the about-block and the exercise, which is
    the one thing always kept in context verbatim.

    Mirrors `internal_testing/run_transcript.py:_build_assignment_text` but omits the
    `Run configuration` block — sandbox_ui chats are open-ended, no planned
    turn count. The leading block describes the AskTIM deployment so the
    tutor can coherently answer "what are you?" / "where am I?" questions;
    it lives at `curriculum/about_asktim.txt` and is only read here so
    `tutor/` and the bulk-transcript runners stay unaware of it.

    ``include_course`` / ``include_syllabus`` / ``include_lectures`` are
    sandbox_ui additions: when False, the corresponding built-in on-disk file
    (``course.txt`` / ``syllabus.txt`` / lecture transcripts) is dropped so
    testers can compare tutor behaviour with and without that material in
    context.
    """
    course_dir = _CURRICULUM_DIR / course if course else None
    # Course + syllabus go in the prompt only in full_context; in rag /
    # exercise_only they're retrieved or omitted (the exercise still always goes in).
    include_course_material = context_mode == "full_context"

    parts: list[str] = []

    about_text = load_about_asktim()
    if about_text:
        parts.append("About yourself:\n" + about_text)

    if include_course_material:
        # Course context — gated by the include_course toggle.
        if include_course and course_dir is not None:
            course_path = course_dir / "course.txt"
            if course_path.is_file():
                parts.append(
                    "Course context:\n" + course_path.read_text(encoding="utf-8").strip()
                )

        # Syllabus — gated by the include_syllabus toggle.
        if include_syllabus and course_dir is not None:
            syllabus_path = course_dir / "syllabus.txt"
            if syllabus_path.is_file():
                parts.append(
                    "Syllabus:\n" + syllabus_path.read_text(encoding="utf-8").strip()
                )

        # Lectures — gated by the include_lectures toggle.
        if include_lectures and course:
            _lectures = load_lecture_transcripts(course)
            if _lectures:
                parts.append("Lecture transcripts:\n" + _lectures)

    # Exercise — read exercise_<NN>.txt or practice_<NN>.txt.
    _path = (
        practice_path(course, exercise)
        if exercise_kind == "practice"
        else exercise_path(course, exercise)
    )
    resolved_exercise = _path.read_text(encoding="utf-8").strip()
    parts.append("Exercise:\n" + resolved_exercise)

    # Tutor-only correct-answer reference, paired directly to the current problem
    # (never retrieved via RAG, never shown to the student). Skipped for
    # problems with no solution file yet.
    solution = read_solution(course, exercise, kind=exercise_kind)
    if solution.strip():
        parts.append(SOLUTION_CONTEXT_LABEL + solution.strip())

    return "\n\n".join(parts)


class SandboxTutorBridge(TutorBridge):
    """Adds sandbox_ui's RAG / include-toggle behavior."""

    def cache_key(self, tutor: str, course: str, exercise: str, **ctx):
        """Cache key for the built context, keyed on the sandbox include-toggles/kind/mode."""
        return (
            tutor,
            course,
            exercise,
            ctx.get("include_course", True),
            ctx.get("include_syllabus", True),
            ctx.get("include_lectures", True),
            ctx.get("exercise_kind", "exercise"),
            ctx.get("context_mode", "full_context"),
        )

    def build_assignment_text(self, course: str, exercise: str, **ctx) -> str:
        """Build the assignment text block, honoring include toggles and context mode."""
        return build_assignment_text(
            course,
            exercise,
            exercise_kind=ctx.get("exercise_kind", "exercise"),
            include_course=ctx.get("include_course", True),
            include_syllabus=ctx.get("include_syllabus", True),
            include_lectures=ctx.get("include_lectures", True),
            context_mode=ctx.get("context_mode", "full_context"),
        )


_bridge = SandboxTutorBridge()


def get_tutor_reply(
    *,
    course: str,
    exercise: str,
    tutor: str,
    history: list[dict],
    new_student_message: str,
    images: list | None = None,
    exercise_kind: str = "exercise",
    include_course: bool = True,
    include_syllabus: bool = True,
    include_lectures: bool = True,
    context_mode: str | None = None,
) -> dict:
    """Return one tutor reply for the given conversation state.

    Args:
        course: course slug under ``curriculum/`` (e.g. ``cities_and_climate_change``)
        exercise: exercise number, non-padded (e.g. ``"4"``)
        tutor: tutor prompt stem (e.g. ``"tutor_06"``)
        history: prior conversation as ``[{"role": "student"|"tutor", "content": str}, ...]``
        new_student_message: the latest student turn to respond to
        include_syllabus: whether to fold the course syllabus into context

    Returns:
        ``{"reply": str, "reasoning": str | None}`` — reasoning is the
        tutor's hidden ``pedagogical-reasoning`` field; ``None`` if parsing
        the tutor's JSON failed.
    """
    return _bridge.get_tutor_reply(
        course=course,
        exercise=exercise,
        tutor=tutor,
        history=history,
        new_student_message=new_student_message,
        images=images,
        exercise_kind=exercise_kind,
        include_course=include_course,
        include_syllabus=include_syllabus,
        include_lectures=include_lectures,
        context_mode=context_mode,
    )


def stream_tutor_reply(
    *,
    course: str,
    exercise: str,
    tutor: str,
    history: list[dict],
    new_student_message: str,
    images: list | None = None,
    exercise_kind: str = "exercise",
    include_course: bool = True,
    include_syllabus: bool = True,
    include_lectures: bool = True,
    context_mode: str | None = None,
):
    """Stream a tutor reply as a sequence of event dicts.

    Yields:
        ``{"type": "delta", "text": "..."}`` for each batch of visible
        student-facing characters, then exactly one terminal event:
        ``{"type": "done", "reply": "...", "reasoning": "..." | None}``.

    Routes are responsible for re-shaping these into SSE frames.
    """
    return _bridge.stream_tutor_reply(
        course=course,
        exercise=exercise,
        tutor=tutor,
        history=history,
        new_student_message=new_student_message,
        images=images,
        exercise_kind=exercise_kind,
        include_course=include_course,
        include_syllabus=include_syllabus,
        include_lectures=include_lectures,
        context_mode=context_mode,
    )
