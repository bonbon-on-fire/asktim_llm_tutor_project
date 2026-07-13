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
overrides that base's hooks to add sandbox_ui's RAG / custom-context /
include-toggle behavior; the module-level functions at the bottom are a thin
wrapper around one shared instance, preserving the exact public names and
call signatures `sandbox_ui/routes/*` import.
"""

from __future__ import annotations

import re
from pathlib import Path

from tutor.run_tutor import load_system_prompt
from ui_core.tutor_bridge import TutorBridge, _resolve_context_mode
from utils.curriculum import (
    SOLUTION_CONTEXT_LABEL,
    exercise_path,
    load_about_asktim,
    practice_path,
    read_solution,
)
from utils.figures import discover_figures
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
    course_text: str | None = None,
    exercise_text: str | None = None,
    syllabus_text: str | None = None,
    lectures_text: str | None = None,
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

    about_text = load_about_asktim()
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

        # Lectures — custom text wins; otherwise the built-in toggle gates the
        # course's lectures/*.txt transcripts (mirrors the syllabus handling).
        if lectures_text is not None:
            if lectures_text.strip():
                parts.append("Lecture transcripts:\n" + lectures_text.strip())
        elif include_lectures and course:
            _lectures = load_lecture_transcripts(course)
            if _lectures:
                parts.append("Lecture transcripts:\n" + _lectures)

    # Exercise — custom text wins; otherwise read exercise_<NN>.txt or practice_<NN>.txt.
    if exercise_text is not None:
        resolved_exercise = exercise_text.strip()
    else:
        _path = (
            practice_path(course, exercise)
            if exercise_kind == "practice"
            else exercise_path(course, exercise)
        )
        resolved_exercise = _path.read_text(encoding="utf-8").strip()
    parts.append("Exercise:\n" + resolved_exercise)

    # Tutor-only correct-answer reference, paired directly to the current problem
    # (never retrieved via RAG, never shown to the student). Skipped for custom
    # exercise text (no matching file) and problems with no solution file yet.
    if exercise_text is None:
        solution = read_solution(course, exercise, kind=exercise_kind)
        if solution.strip():
            parts.append(SOLUTION_CONTEXT_LABEL + solution.strip())

    return "\n\n".join(parts)


def _render_custom_tutor_prompt(prompt_text: str, assignment_override: str) -> str:
    """Render a tester-supplied tutor prompt, injecting the assignment.

    Mirrors `tutor.load_system_prompt`'s `<Assignment>` substitution, but for
    raw prompt text instead of a file. If the custom prompt has no
    `<Assignment>` block, the assignment is appended so the tutor still sees
    the exercise.
    """
    if "<Assignment>" in prompt_text and "</Assignment>" in prompt_text:
        # Replacement *function* so backslashes in the assignment (e.g. LaTeX
        # like \sum) are inserted literally; a template string would make re.sub
        # treat them as escapes ("bad escape \s").
        replacement = f"<Assignment>\n{assignment_override.strip()}\n</Assignment>"
        rendered = re.sub(
            r"<Assignment>.*?</Assignment>",
            lambda _m: replacement,
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
    lectures_text: str | None = None,
) -> bool:
    """True if any custom-context override text is provided (non-None)."""
    return any(
        v is not None
        for v in (course_text, exercise_text, syllabus_text, custom_tutor_prompt, lectures_text)
    )


class SandboxTutorBridge(TutorBridge):
    """Adds sandbox_ui's RAG / custom-context / include-toggle behavior."""

    def prepare_ctx(self, course: str, **ctx) -> dict:
        """Annotate ctx with has_custom and the resolved context_mode before the turn is built."""
        course_text = ctx.get("course_text")
        exercise_text = ctx.get("exercise_text")
        syllabus_text = ctx.get("syllabus_text")
        lectures_text = ctx.get("lectures_text")
        custom_tutor_prompt = ctx.get("custom_tutor_prompt")
        has_custom = _has_custom(
            course_text, exercise_text, syllabus_text, custom_tutor_prompt, lectures_text
        )
        ctx["has_custom"] = has_custom
        ctx["context_mode"] = _resolve_context_mode(
            course, has_custom, requested=ctx.get("context_mode")
        )
        return ctx

    def cache_key(self, tutor: str, course: str, exercise: str, **ctx):
        """Cache key for the built context, or None when custom context makes it uncacheable."""
        # Custom context is one-off — never cache it (mirrors the original
        # `if not custom: ...` gating around cache reads/writes).
        if ctx.get("has_custom"):
            return None
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
        """Build the assignment text block, honoring include toggles, custom overrides, and context mode."""
        return build_assignment_text(
            course,
            exercise,
            exercise_kind=ctx.get("exercise_kind", "exercise"),
            include_course=ctx.get("include_course", True),
            include_syllabus=ctx.get("include_syllabus", True),
            include_lectures=ctx.get("include_lectures", True),
            course_text=ctx.get("course_text"),
            exercise_text=ctx.get("exercise_text"),
            syllabus_text=ctx.get("syllabus_text"),
            lectures_text=ctx.get("lectures_text"),
            context_mode=ctx.get("context_mode", "full_context"),
        )

    def build_system_prompt(self, tutor: str, assignment_text: str, **ctx) -> str:
        """Build the system prompt, using a custom tutor prompt if given, else the built-in tutor stem."""
        custom_tutor_prompt = ctx.get("custom_tutor_prompt")
        if custom_tutor_prompt is not None:
            return _render_custom_tutor_prompt(custom_tutor_prompt, assignment_text)
        return load_system_prompt(tutor, assignment_override=assignment_text)

    def turn_attachments(self, course: str, exercise: str, images: list | None, **ctx):
        """Curriculum figures + uploads, with figures gated off for custom exercises.

        Curriculum figures attach only when the course *and* exercise are
        built-ins (no custom override) — a tester's typed-in custom exercise
        has no figures folder on disk.
        """
        course_text = ctx.get("course_text")
        exercise_text = ctx.get("exercise_text")
        figures: list = []
        if course and course_text is None and exercise_text is None:
            figures = discover_figures(course, exercise)
        combined = [*figures, *(images or [])]
        return combined or None


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
    course_text: str | None = None,
    exercise_text: str | None = None,
    syllabus_text: str | None = None,
    lectures_text: str | None = None,
    custom_tutor_prompt: str | None = None,
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
        course_text / exercise_text / syllabus_text / custom_tutor_prompt:
            one-off custom context overrides (see ``build_assignment_text``)

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
        course_text=course_text,
        exercise_text=exercise_text,
        syllabus_text=syllabus_text,
        lectures_text=lectures_text,
        custom_tutor_prompt=custom_tutor_prompt,
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
    course_text: str | None = None,
    exercise_text: str | None = None,
    syllabus_text: str | None = None,
    lectures_text: str | None = None,
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
        course_text=course_text,
        exercise_text=exercise_text,
        syllabus_text=syllabus_text,
        lectures_text=lectures_text,
        custom_tutor_prompt=custom_tutor_prompt,
        context_mode=context_mode,
    )
