"""Shared conversation persistence helpers for the web apps.

The one place that creates / resolves / appends to ``Conversation`` and
``Message`` rows. Route handlers call the per-app wrapper in
``<app>/services/conversation.py``; they never construct DB models inline.

The ORM model classes are passed in rather than imported: each app declares
its own ``Conversation`` / ``Message`` / ``UploadedImage`` on its own ``Base``
(the ``Conversation`` schemas diverge — sandbox_ui adds columns), so these
helpers stay app-agnostic and each app binds its own models (bundled in a
:class:`Models`) via a thin wrapper in ``<app>/services/conversation.py``.

Two behaviors also diverge per app and are parameterized rather than baked in:

- ``find_or_create_conversation``: sandbox_ui stores extra ``Conversation``
  columns on insert (``extra_fields``); main_ui has none.
- ``get_messages_for_conversation``: sandbox_ui includes the tutor's hidden
  ``pedagogical_reasoning`` (``include_reasoning=True``, a dev/TA tool);
  main_ui excludes it (student-facing policy).
- ``list_conversations_for_username`` / ``_summarize_conversation``: sandbox_ui
  merges extra summary keys via ``summarize_extra``; main_ui has none.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class Models:
    """Bundle of the per-app ORM classes these helpers operate on."""

    Conversation: type
    Message: type
    UploadedImage: type
    UploadedFile: type | None = None


class WrongSessionError(Exception):
    """Raised when a request supplies a conversation_id that isn't owned by
    the current session_id (or doesn't exist at all)."""


def find_or_create_conversation(
    db: Session,
    *,
    models: Models,
    session_id: str,
    conversation_id: UUID | None,
    course: str,
    exercise_number: str,
    tutor_prompt: str,
    username: str | None = None,
    extra_fields: dict[str, Any] | None = None,
) -> Any:
    """Resolve to an existing conversation or insert a new one.

    Raises:
        WrongSessionError: if `conversation_id` was provided but either
            doesn't exist or belongs to a different session.
    """
    if conversation_id is not None:
        existing = db.get(models.Conversation, conversation_id)
        if existing is None:
            raise WrongSessionError()
        # Accept if the current session owns it OR if the current username
        # matches the conversation's username (enables cross-browser continuity
        # once the student has linked their username).
        same_session = existing.session_id == session_id
        same_username = bool(username) and existing.username == username
        if not (same_session or same_username):
            raise WrongSessionError()
        return existing

    convo = models.Conversation(
        session_id=session_id,
        username=username,
        course=course,
        exercise_number=exercise_number,
        tutor_prompt=tutor_prompt,
        **(extra_fields or {}),
    )
    db.add(convo)
    db.flush()  # populate convo.id before the caller uses it
    return convo


def append_exchange(
    db: Session,
    *,
    models: Models,
    conversation: Any,
    student_text: str,
    tutor_text: str,
    pedagogical_reasoning: str | None,
) -> tuple[Any, Any]:
    """Insert the student/tutor message pair for the next turn.

    Both messages share a single turn number (1-indexed). Bumps
    `conversation.last_active_at`.
    """
    next_turn = _next_turn_number(db, conversation, models=models)

    student_msg = models.Message(
        conversation_id=conversation.id,
        turn=next_turn,
        role="student",
        content=student_text,
    )
    tutor_msg = models.Message(
        conversation_id=conversation.id,
        turn=next_turn,
        role="tutor",
        content=tutor_text,
        pedagogical_reasoning=pedagogical_reasoning,
    )
    db.add(student_msg)
    db.add(tutor_msg)
    conversation.last_active_at = datetime.now(timezone.utc)
    db.flush()
    return student_msg, tutor_msg


def start_exchange_student_only(
    db: Session,
    *,
    models: Models,
    conversation: Any,
    student_text: str,
) -> Any:
    """Insert just the student message at the start of a streaming turn.

    Used by the SSE chat path so the student message is persisted before
    we begin streaming the tutor reply. If the stream fails mid-flight,
    the student row remains (no orphan tutor row) and the next call
    naturally picks the next turn number.
    """
    next_turn = _next_turn_number(db, conversation, models=models)
    student_msg = models.Message(
        conversation_id=conversation.id,
        turn=next_turn,
        role="student",
        content=student_text,
    )
    db.add(student_msg)
    conversation.last_active_at = datetime.now(timezone.utc)
    db.flush()
    return student_msg


def complete_exchange_tutor(
    db: Session,
    *,
    models: Models,
    conversation: Any,
    turn: int,
    tutor_text: str,
    pedagogical_reasoning: str | None,
) -> Any:
    """Insert the tutor reply for a turn previously opened by
    :func:`start_exchange_student_only`.
    """
    tutor_msg = models.Message(
        conversation_id=conversation.id,
        turn=turn,
        role="tutor",
        content=tutor_text,
        pedagogical_reasoning=pedagogical_reasoning,
    )
    db.add(tutor_msg)
    conversation.last_active_at = datetime.now(timezone.utc)
    db.flush()
    return tutor_msg


def _content_with_attachments(content: str, attachments) -> str:
    """Append each attachment's extracted text to a message's model-facing content."""
    if not attachments:
        return content
    blocks = "".join(
        f"\n\n[Attachment: {a.filename}]\n{a.extracted_text}" for a in attachments
    )
    return f"{content}{blocks}"


def get_history_for_tutor(db: Session, conversation: Any, *, models: Models) -> list[dict]:
    """Return prior messages as [{role, content}, ...] in chronological order.

    Shape matches what `tutor_bridge.get_tutor_reply` expects, so callers can
    pass the result straight through. Student-turn ``uploaded_files`` extracted
    text is re-injected into ``content`` here (not stored/displayed) so
    attachments stay visible to the tutor on later turns. Files are batch
    loaded via `_files_by_message` (one query for the whole conversation)
    rather than lazily per message, mirroring how `_images_by_message` avoids
    N+1 lookups in `get_messages_for_conversation`.
    """
    stmt = (
        select(models.Message)
        .where(models.Message.conversation_id == conversation.id)
        .order_by(models.Message.turn, models.Message.id)
    )
    msgs = db.execute(stmt).scalars().all()
    files_by_message = _files_by_message(db, conversation, models=models)
    out: list[dict] = []
    for m in msgs:
        content = m.content
        if m.role == "student":
            atts = files_by_message.get(m.id, [])
            content = _content_with_attachments(content, atts)
        out.append({"role": m.role, "content": content})
    return out


def _files_by_message(
    db: Session, conversation: Any, *, models: Models
) -> dict[int, list[Any]]:
    """Map message_id -> [UploadedFile, ...] for this conversation's messages.

    Mirrors `_images_by_message`'s batched-query pattern: a single query over
    `models.UploadedFile` for the whole conversation instead of a lazy load
    per message. No-op (returns `{}`) when the app doesn't bind `UploadedFile`.
    """
    if getattr(models, "UploadedFile", None) is None:
        return {}
    stmt = (
        select(models.UploadedFile)
        .join(models.Message, models.UploadedFile.message_id == models.Message.id)
        .where(models.Message.conversation_id == conversation.id)
        .order_by(models.UploadedFile.id)
    )
    out: dict[int, list[Any]] = {}
    for f in db.execute(stmt).scalars().all():
        out.setdefault(f.message_id, []).append(f)
    return out


def count_student_messages(db: Session, conversation: Any, *, models: Models) -> int:
    """Number of student-role messages in this conversation.

    Step 7's username modal triggers when this reaches 3.
    """
    stmt = (
        select(func.count(models.Message.id))
        .where(models.Message.conversation_id == conversation.id)
        .where(models.Message.role == "student")
    )
    return int(db.execute(stmt).scalar_one())


def list_conversations_for_username(
    db: Session,
    username: str,
    *,
    models: Models,
    summarize_extra: Callable[[Any], dict] | None = None,
) -> list[dict]:
    """Return all conversations linked to the given username, most-recently-active
    first. Each entry is a JSON-serializable dict suitable for the history API.
    """
    if not username:
        return []
    convos = (
        db.query(models.Conversation)
        .filter(models.Conversation.username == username)
        .order_by(models.Conversation.last_active_at.desc())
        .all()
    )
    return [
        _summarize_conversation(db, c, models=models, summarize_extra=summarize_extra)
        for c in convos
    ]


def get_conversation_for_viewer(
    db: Session,
    conversation_id,
    session_id: str,
    username: str | None,
    *,
    models: Models,
) -> Any | None:
    """Return a Conversation if the viewer either owns it via `session_id`
    (anonymous, same browser) or has the matching username (cross-browser).
    Otherwise return None so callers can map to 404 without leaking
    existence.
    """
    convo = db.get(models.Conversation, conversation_id)
    if convo is None:
        return None
    if convo.session_id == session_id:
        return convo
    if username and convo.username == username:
        return convo
    return None


def get_message_for_viewer(
    db: Session,
    message_id: int,
    session_id: str,
    username: str | None,
    *,
    models: Models,
) -> Any | None:
    """Return a Message if the viewer owns its conversation, else None.

    Reuses the same ownership rule as :func:`get_conversation_for_viewer`
    (session_id match, or username match) so callers can map a miss to 403
    without leaking whether the message exists.
    """
    msg = db.get(models.Message, message_id)
    if msg is None:
        return None
    convo = get_conversation_for_viewer(
        db, msg.conversation_id, session_id, username, models=models
    )
    return msg if convo is not None else None


def set_message_rating(db: Session, message: Any, rating: int) -> Any:
    """Set a message's thumb rating (-1/0/1) and flush. Caller commits."""
    message.rating = rating
    db.flush()
    return message


def get_messages_for_conversation(
    db: Session,
    conversation: Any,
    *,
    models: Models,
    include_reasoning: bool = False,
    include_retrieved: bool = False,
) -> list[dict]:
    """Return chronologically ordered messages as JSON-friendly dicts.

    Each entry carries ``id`` and ``rating`` (the per-message thumb, -1/0/1) so
    the client can restore thumb state and target ``POST /api/message/<id>/rating``
    when replaying history.

    ``pedagogical_reasoning`` (the tutor's hidden reasoning) is included only
    when ``include_reasoning`` is set — sandbox_ui is a dev/TA tool where
    reviewers may inspect it (same policy as the database_ui review
    dashboard); main_ui excludes it (student-facing policy).
    """
    stmt = (
        select(models.Message)
        .where(models.Message.conversation_id == conversation.id)
        .order_by(models.Message.turn, models.Message.id)
    )
    messages = db.execute(stmt).scalars().all()

    # Attach image metadata (id + mime only — never the bytes) so the frontend
    # can render thumbnails via GET /api/image/<id>. One grouped query avoids
    # N+1 lookups.
    images_by_message = _images_by_message(db, [m.id for m in messages], models=models)
    # Sibling metadata for non-image attachments: id + filename + kind only —
    # never extracted_text or the raw bytes, which must not reach the browser.
    attachments_by_message = _attachments_by_message(
        db, [m.id for m in messages], models=models
    )
    result = []
    for m in messages:
        entry = {
            "id": m.id,
            "turn": m.turn,
            "role": m.role,
            "content": m.content,
            # Per-message thumb rating (-1/0/1); lets history replay restore the
            # thumbs state. Legacy rows predating the column read back NULL -> 0.
            "rating": getattr(m, "rating", 0) or 0,
        }
        if include_reasoning:
            entry["pedagogical_reasoning"] = m.pedagogical_reasoning
        if include_retrieved:
            raw = getattr(m, "retrieved_context", None)
            if raw:
                import json as _json

                try:
                    entry["retrieved"] = _json.loads(raw)
                except (ValueError, TypeError):
                    pass
        entry["images"] = images_by_message.get(m.id, [])
        entry["attachments"] = attachments_by_message.get(m.id, [])
        result.append(entry)
    return result


def _images_by_message(
    db: Session, message_ids: list[int], *, models: Models
) -> dict[int, list[dict]]:
    """Map message_id -> [{"id", "mime_type"}, ...] for the given messages."""
    if not message_ids:
        return {}
    stmt = (
        select(
            models.UploadedImage.id,
            models.UploadedImage.message_id,
            models.UploadedImage.mime_type,
        )
        .where(models.UploadedImage.message_id.in_(message_ids))
        .order_by(models.UploadedImage.id)
    )
    out: dict[int, list[dict]] = {}
    for img_id, msg_id, mime in db.execute(stmt).all():
        out.setdefault(msg_id, []).append({"id": img_id, "mime_type": mime})
    return out


def _attachments_by_message(
    db: Session, message_ids: list[int], *, models: Models
) -> dict[int, list[dict]]:
    """Map message_id -> [{"id", "filename", "kind"}, ...] for the given messages.

    Column-scoped query — never selects ``extracted_text`` or ``data`` — since
    this metadata is what the message-list API sends to the browser. No-op
    (returns ``{}``) when the app doesn't bind ``UploadedFile``.
    """
    if not message_ids or getattr(models, "UploadedFile", None) is None:
        return {}
    stmt = (
        select(
            models.UploadedFile.id,
            models.UploadedFile.message_id,
            models.UploadedFile.filename,
            models.UploadedFile.kind,
        )
        .where(models.UploadedFile.message_id.in_(message_ids))
        .order_by(models.UploadedFile.id)
    )
    out: dict[int, list[dict]] = {}
    for file_id, msg_id, filename, kind in db.execute(stmt).all():
        out.setdefault(msg_id, []).append(
            {"id": file_id, "filename": filename, "kind": kind}
        )
    return out


def _summarize_conversation(
    db: Session,
    c: Any,
    *,
    models: Models,
    summarize_extra: Callable[[Any], dict] | None = None,
) -> dict:
    """Build the summary dict used by the history endpoint."""
    msg_count = db.execute(
        select(func.count(models.Message.id)).where(
            models.Message.conversation_id == c.id
        )
    ).scalar_one()

    last_message_stmt = (
        select(models.Message.content)
        .where(models.Message.conversation_id == c.id)
        .order_by(models.Message.id.desc())
        .limit(1)
    )
    last_message = db.execute(last_message_stmt).scalar_one_or_none()

    snippet: str | None
    if last_message:
        snippet = last_message.strip()[:80]
        if len(last_message) > 80:
            snippet = snippet.rstrip() + "…"
    else:
        snippet = None

    summary = {
        "id": str(c.id),
        "course": c.course,
        "exercise_number": c.exercise_number,
        "tutor_prompt": c.tutor_prompt,
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "last_active_at": c.last_active_at.isoformat() if c.last_active_at else None,
        "message_count": int(msg_count),
        "last_message_snippet": snippet,
    }
    if summarize_extra is not None:
        summary.update(summarize_extra(c))
    return summary


def backfill_username_for_session(
    db: Session, session_id: str, username: str, *, models: Models
) -> int:
    """Set `username` on every Conversation row for this session that doesn't
    already have one. Returns the number of rows touched.

    Used by Step 7's username modal to retroactively link anonymous
    conversations to a student once they provide their username.
    """
    stmt = (
        update(models.Conversation)
        .where(models.Conversation.session_id == session_id)
        .where(models.Conversation.username.is_(None))
        .values(username=username)
        .execution_options(synchronize_session="fetch")
    )
    result = db.execute(stmt)
    db.flush()
    return int(result.rowcount or 0)


def _next_turn_number(db: Session, conversation: Any, *, models: Models) -> int:
    """Return the next 1-based turn number for *conversation* (max existing turn + 1)."""
    stmt = select(func.max(models.Message.turn)).where(
        models.Message.conversation_id == conversation.id
    )
    current_max = db.execute(stmt).scalar_one()
    return (current_max or 0) + 1
