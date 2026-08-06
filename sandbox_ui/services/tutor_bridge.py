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

from ui_core.tutor_bridge import TutorBridge, _resolve_provider
from utils.curriculum import (
    SOLUTION_CONTEXT_LABEL,
    exercise_path,
    load_about_asktim,
    practice_path,
    read_pinned_context,
    read_solution,
    subproblem_label,
)
from utils.lectures import load_lecture_transcripts


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"


def build_assignment_text(
    course: str,
    exercise: str,
    *,
    exercise_kind: str = "exercise",
    include_lectures: bool = True,
    context_mode: str = "full_context",
    focus_problem: int | None = None,
) -> str:
    """Concatenate about_asktim.txt + pinned reference docs + optional lectures + exercise_<NN>.txt.

    ``context_mode`` controls how much course-level material is baked into the
    prompt. Pinned reference docs live in ``curriculum/<course>/pinned/*.txt`` (the
    course description, syllabus, and any other always-on material); they're folded
    in for BOTH ``full_context`` and ``rag`` and correspondingly excluded from the
    RAG index (see ``rag.sources``) so nothing pinned is also retrieved. Lecture
    transcripts (large) are included only in ``full_context``; in ``rag`` they're
    reached via retrieval. ``exercise_only`` drops all course material, leaving only
    the about-block and the exercise, which is always kept.

    Mirrors `internal_testing/run_transcript.py:_build_assignment_text` but omits the
    `Run configuration` block — sandbox_ui chats are open-ended, no planned
    turn count. The leading block describes the AskTIM deployment so the
    tutor can coherently answer "what are you?" / "where am I?" questions;
    it lives at `curriculum/about_asktim.txt` and is only read here so
    `tutor/` and the bulk-transcript runners stay unaware of it.

    ``include_lectures`` is a sandbox_ui addition: when False, the course's lecture
    transcripts are dropped so testers can compare tutor behaviour with and without
    them (full_context only).
    """
    # Pinned reference docs are folded in for full_context AND rag; lectures (large)
    # stay full_context-only (rag retrieves them); exercise_only drops all course
    # material (the exercise still always goes in).
    pin_context = context_mode in ("full_context", "rag")
    include_lecture_transcripts = context_mode == "full_context"

    parts: list[str] = []

    about_text = load_about_asktim()
    if about_text:
        parts.append("About yourself:\n" + about_text)

    # Pinned reference docs (curriculum/<course>/pinned/*.txt) — course description,
    # syllabus, debugging guides, etc. Never retrieved (see rag.sources).
    if pin_context and course:
        pinned = read_pinned_context(course)
        if pinned:
            parts.append(pinned)

    # Lectures (large) — full_context only; gated by the include_lectures toggle.
    if include_lecture_transcripts and include_lectures and course:
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

    # Optional focus directive: names the one sub-problem the student is currently
    # working on (parity with ui_core / main_ui). The whole file still loads below; the
    # directive only marks the focus. Absent/unresolvable -> byte-identical to
    # no-focus output.
    if focus_problem:
        label = subproblem_label(course, exercise, exercise_kind, focus_problem)
        if label:
            parts.append(
                f'Focus: the student is currently working on "{label}".\n'
                "The full set of this week's problems is included below; help "
                "with the focus problem first, and treat the others as reference "
                "unless the student asks about them."
            )

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
        """Cache key for the built context, keyed on the sandbox lectures-toggle/kind/mode."""
        return (
            tutor,
            course,
            exercise,
            ctx.get("include_lectures", True),
            ctx.get("exercise_kind", "exercise"),
            ctx.get("context_mode", "full_context"),
            _resolve_provider(ctx.get("provider")),
            ctx.get("focus_problem"),
        )

    def build_assignment_text(self, course: str, exercise: str, **ctx) -> str:
        """Build the assignment text block, honoring the lectures toggle and context mode."""
        return build_assignment_text(
            course,
            exercise,
            exercise_kind=ctx.get("exercise_kind", "exercise"),
            include_lectures=ctx.get("include_lectures", True),
            context_mode=ctx.get("context_mode", "full_context"),
            focus_problem=ctx.get("focus_problem"),
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
    focus_problem: int | None = None,
    include_lectures: bool = True,
    context_mode: str | None = None,
    provider: str | None = None,
) -> dict:
    """Return one tutor reply for the given conversation state.

    Args:
        course: course slug under ``curriculum/`` (e.g. ``cities_and_climate_change``)
        exercise: exercise number, non-padded (e.g. ``"4"``)
        tutor: tutor prompt stem (e.g. ``"tutor_07"``)
        history: prior conversation as ``[{"role": "student"|"tutor", "content": str}, ...]``
        new_student_message: the latest student turn to respond to
        include_lectures: whether to fold the course lecture transcripts into context

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
        focus_problem=focus_problem,
        include_lectures=include_lectures,
        context_mode=context_mode,
        provider=provider,
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
    focus_problem: int | None = None,
    include_lectures: bool = True,
    context_mode: str | None = None,
    provider: str | None = None,
    history_mode: str = "legacy",
    cached_history: list[dict] | None = None,
):
    """Stream a tutor reply as a sequence of event dicts.

    Yields:
        ``{"type": "delta", "text": "..."}`` for each batch of visible
        student-facing characters, then exactly one terminal event:
        ``{"type": "done", "reply": "...", "reasoning": "..." | None}``.

    Routes are responsible for re-shaping these into SSE frames.

    *history_mode* / *cached_history* thread the cache-friendly interleaved
    history path through to the shared bridge (see
    ``ui_core.tutor_bridge.cached_history_enabled``); ``"legacy"`` (default)
    keeps today's behavior byte-for-byte.
    """
    return _bridge.stream_tutor_reply(
        course=course,
        exercise=exercise,
        tutor=tutor,
        history=history,
        new_student_message=new_student_message,
        images=images,
        exercise_kind=exercise_kind,
        focus_problem=focus_problem,
        include_lectures=include_lectures,
        context_mode=context_mode,
        provider=provider,
        history_mode=history_mode,
        cached_history=cached_history,
    )
