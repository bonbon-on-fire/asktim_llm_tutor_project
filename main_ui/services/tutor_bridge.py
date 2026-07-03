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


def build_assignment_text(course: str, exercise: str) -> str:
    return _bridge.build_assignment_text(course, exercise)


def get_tutor_reply(
    *,
    course: str,
    exercise: str,
    tutor: str,
    history: list[dict],
    new_student_message: str,
    images: list | None = None,
) -> dict:
    """Return one tutor reply for the given conversation state.

    Args:
        course: course slug under ``curriculum/`` (e.g. ``cities_and_climate_change``)
        exercise: zero-padded 2-digit exercise number (e.g. ``"04"``)
        tutor: tutor prompt stem (e.g. ``"tutor_05"``)
        history: prior conversation as ``[{"role": "student"|"tutor", "content": str}, ...]``
        new_student_message: the latest student turn to respond to
        images: optional ``(bytes, mime)`` tuples attached to this student turn

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
    )


def stream_tutor_reply(
    *,
    course: str,
    exercise: str,
    tutor: str,
    history: list[dict],
    new_student_message: str,
    images: list | None = None,
):
    """Stream a tutor reply as a sequence of event dicts.

    Yields:
        ``{"type": "delta", "text": "..."}`` for each batch of visible
        student-facing characters, then exactly one terminal event:
        ``{"type": "done", "reply": "...", "reasoning": "..." | None}``.

    *images* (``(bytes, mime)`` tuples) attach to this student turn as
    multimodal content. Routes are responsible for re-shaping these into SSE
    frames.
    """
    return _bridge.stream_tutor_reply(
        course=course,
        exercise=exercise,
        tutor=tutor,
        history=history,
        new_student_message=new_student_message,
        images=images,
    )
