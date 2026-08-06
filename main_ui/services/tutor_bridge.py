"""Bridge from main_ui to the existing tutor.run_tutor pipeline.

The one place in `main_ui` that talks to `tutor.run_tutor`. Routes call
`get_tutor_reply(...)` here; they never import the upstream tutor API
directly. If the underlying tutor API changes shape later, only this module
needs updating.

No HTTP, no DB, no Flask state — just a thin function from
``(course, exercise, tutor, history, new_student_message)`` to a tutor reply.

The actual control flow lives in :class:`ui_core.tutor_bridge.TutorBridge`;
this module is a thin wrapper around one shared instance, preserving the
exact public names and call signatures `main_ui/routes/*` import.
"""

from __future__ import annotations

from ui_core.tutor_bridge import TutorBridge

_bridge = TutorBridge()


def build_assignment_text(course: str, exercise: str, *, exercise_kind: str = "exercise") -> str:
    """Return the assignment text for a course/exercise|practice via the shared bridge."""
    return _bridge.build_assignment_text(course, exercise, exercise_kind=exercise_kind)


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
) -> dict:
    """Return one tutor reply for the given conversation state.

    Args:
        course: course slug under ``curriculum/`` (e.g. ``cities_and_climate_change``)
        exercise: exercise number, non-padded (e.g. ``"4"``)
        tutor: tutor prompt stem (e.g. ``"tutor_05"``)
        history: prior conversation as ``[{"role": "student"|"tutor", "content": str}, ...]``
        new_student_message: the latest student turn to respond to
        images: optional ``(bytes, mime)`` tuples attached to this student turn
        focus_problem: optional sub-problem number the student is focused on

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
    history_mode: str = "legacy",
    cached_history: list[dict] | None = None,
):
    """Stream a tutor reply as a sequence of event dicts.

    Yields:
        ``{"type": "delta", "text": "..."}`` for each batch of visible
        student-facing characters, then exactly one terminal event:
        ``{"type": "done", "reply": "...", "reasoning": "..." | None}``.

    *images* (``(bytes, mime)`` tuples) attach to this student turn as
    multimodal content. Routes are responsible for re-shaping these into SSE
    frames.

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
        history_mode=history_mode,
        cached_history=cached_history,
    )
