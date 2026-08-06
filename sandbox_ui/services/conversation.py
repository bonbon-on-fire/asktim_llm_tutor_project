"""Conversation persistence helpers for sandbox_ui.

Thin wrapper over :mod:`ui_core.services.conversation`: binds sandbox_ui's own
model classes (its ``Conversation`` schema carries extra columns — see
``sandbox_ui/db/models.py``) to the shared, app-agnostic logic. Route handlers
call these; they never construct DB models inline.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.orm import Session

from sandbox_ui.db.models import Conversation, Message, UploadedFile, UploadedImage
from ui_core.services import conversation as _shared
from ui_core.services.conversation import Models, WrongSessionError
from utils.curriculum import load_course_name

_MODELS = Models(
    Conversation=Conversation,
    Message=Message,
    UploadedImage=UploadedImage,
    UploadedFile=UploadedFile,
)

# Re-exported unchanged so `except WrongSessionError` keeps working at call sites.
WrongSessionError = WrongSessionError


def find_or_create_conversation(
    db: Session,
    *,
    session_id: str,
    conversation_id: UUID | None,
    course: str,
    exercise_number: str,
    exercise_kind: str = "exercise",
    tutor_prompt: str,
    focus_problem: int | None = None,
    username: str | None = None,
    lectures_enabled: bool = True,
    context_mode: str | None = None,
    provider: str | None = None,
) -> Conversation:
    """Resolve to an existing conversation or insert a new one.

    Raises:
        WrongSessionError: if `conversation_id` was provided but either
            doesn't exist or belongs to a different session.
    """
    return _shared.find_or_create_conversation(
        db,
        models=_MODELS,
        session_id=session_id,
        conversation_id=conversation_id,
        course=course,
        exercise_number=exercise_number,
        tutor_prompt=tutor_prompt,
        username=username,
        extra_fields={
            "exercise_kind": exercise_kind,
            "focus_problem": focus_problem,
            "lectures_enabled": lectures_enabled,
            "context_mode": context_mode,
            "provider": provider,
        },
    )


def append_exchange(
    db: Session,
    *,
    conversation: Conversation,
    student_text: str,
    tutor_text: str,
    pedagogical_reasoning: str | None,
) -> tuple[Message, Message]:
    """Insert the student/tutor message pair for the next turn."""
    return _shared.append_exchange(
        db,
        models=_MODELS,
        conversation=conversation,
        student_text=student_text,
        tutor_text=tutor_text,
        pedagogical_reasoning=pedagogical_reasoning,
    )


def start_exchange_student_only(
    db: Session,
    *,
    conversation: Conversation,
    student_text: str,
) -> Message:
    """Insert just the student message at the start of a streaming turn."""
    return _shared.start_exchange_student_only(
        db, models=_MODELS, conversation=conversation, student_text=student_text
    )


def complete_exchange_tutor(
    db: Session,
    *,
    conversation: Conversation,
    turn: int,
    tutor_text: str,
    pedagogical_reasoning: str | None,
    retrieved_context: str | None = None,
    cost_usd: float | None = None,
    usage_json: str | None = None,
) -> Message:
    """Insert the tutor reply for a turn previously opened by
    :func:`start_exchange_student_only`.

    ``retrieved_context`` is a JSON string of the RAG chunks retrieved for this
    turn (``[{source, score, chars, text}]``), or ``None`` for non-RAG turns.
    ``cost_usd`` / ``usage_json`` carry the turn's estimated cost + breakdown.
    """
    msg = _shared.complete_exchange_tutor(
        db,
        models=_MODELS,
        conversation=conversation,
        turn=turn,
        tutor_text=tutor_text,
        pedagogical_reasoning=pedagogical_reasoning,
        cost_usd=cost_usd,
        usage_json=usage_json,
    )
    if retrieved_context is not None:
        msg.retrieved_context = retrieved_context
    return msg


def get_history_for_tutor(db: Session, conversation: Conversation) -> list[dict]:
    """Return prior messages as [{role, content}, ...] in chronological order."""
    return _shared.get_history_for_tutor(db, conversation, models=_MODELS)


def get_cached_history_for_tutor(db: Session, conversation: Conversation) -> list[dict]:
    """Per prior completed turn: {student_content, rag_text, tutor_json}."""
    return _shared.get_cached_history_for_tutor(db, conversation, models=_MODELS)


def count_student_messages(db: Session, conversation: Conversation) -> int:
    """Number of student-role messages in this conversation."""
    return _shared.count_student_messages(db, conversation, models=_MODELS)


def _summarize_extra(c: Conversation) -> dict:
    """Sandbox-only summary keys layered on top of the shared summary dict."""
    return {
        "course_name": load_course_name(c.course),
        "exercise_kind": c.exercise_kind or "exercise",
        "lectures_enabled": c.lectures_enabled is None or bool(c.lectures_enabled),
    }


def list_conversations_for_username(db: Session, username: str) -> list[dict]:
    """Return all conversations linked to the given username, most-recently-active
    first. Each entry is a JSON-serializable dict suitable for the history API.
    """
    return _shared.list_conversations_for_username(
        db, username, models=_MODELS, summarize_extra=_summarize_extra
    )


def get_conversation_for_viewer(
    db: Session,
    conversation_id,
    session_id: str,
    username: str | None,
) -> Conversation | None:
    """Return a Conversation if the viewer either owns it via `session_id`
    (anonymous, same browser) or has the matching username (cross-browser).
    """
    return _shared.get_conversation_for_viewer(
        db, conversation_id, session_id, username, models=_MODELS
    )


def get_message_for_viewer(
    db: Session, message_id: int, session_id: str, username: str | None
) -> Message | None:
    """Return a Message if the viewer owns its conversation, else None."""
    return _shared.get_message_for_viewer(
        db, message_id, session_id, username, models=_MODELS
    )


def set_message_rating(db: Session, message: Message, rating: int) -> Message:
    """Set a tutor message's thumb rating (-1/0/1) and flush. Caller commits."""
    return _shared.set_message_rating(db, message, rating)


def get_messages_for_conversation(
    db: Session, conversation: Conversation
) -> list[dict]:
    """Return chronologically ordered messages as JSON-friendly dicts.

    Includes ``pedagogical_reasoning`` (the tutor's hidden reasoning): the
    Sandbox is a dev/TA tool, so reviewers may inspect it — same policy as the
    database_ui review dashboard, unlike the student-facing main_ui.
    """
    return _shared.get_messages_for_conversation(
        db,
        conversation,
        models=_MODELS,
        include_reasoning=True,
        include_retrieved=True,
        include_cost=True,
    )


def backfill_username_for_session(
    db: Session, session_id: str, username: str
) -> int:
    """Set `username` on every Conversation row for this session that doesn't
    already have one. Returns the number of rows touched.
    """
    return _shared.backfill_username_for_session(
        db, session_id, username, models=_MODELS
    )
