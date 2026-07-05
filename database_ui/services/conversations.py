"""Read-only queries backing the review UI.

Unlike the live apps' history endpoints (which scope to the current viewer's
session/email), these return EVERY conversation — that's the whole point of a
review tool. All functions are read-only.

Identity is ``email`` (there is no student-ID column in either schema). Rows
without an email are anonymous; callers render a placeholder.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database_ui.courses import course_display_name
from database_ui.db.models import Conversation, Message, UploadedImage


def list_all_conversations(
    db: Session,
    *,
    sort: str = "date",
    limit: int | None = None,
    offset: int = 0,
) -> list[dict]:
    """Return summaries for all conversations.

    ``sort``:
        - ``"date"`` (default): most-recently-active first.
        - ``"student"``: grouped by email (named students first, anonymous last),
          then most-recently-active within each.

    ``limit`` / ``offset`` paginate the conversation list (counts/snippets are
    fetched only for the page returned, so this stays cheap on large tables).
    """
    order = _order_by(sort)
    stmt = select(Conversation).order_by(*order)
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
    convos = db.execute(stmt).scalars().all()

    ids = [c.id for c in convos]
    counts = _message_counts(db, ids)
    snippets = _last_message_snippets(db, ids)
    return [_summarize(c, counts, snippets) for c in convos]


def get_conversation(db: Session, conversation_id: UUID) -> Conversation | None:
    """Fetch one conversation by id (no ownership check — review sees all)."""
    return db.get(Conversation, conversation_id)


def get_messages_for_conversation(db: Session, conversation: Conversation) -> list[dict]:
    """Chronologically ordered messages as JSON-friendly dicts.

    Includes ``pedagogical_reasoning`` (the tutor's hidden reasoning) — reviewers
    are explicitly allowed to see it, unlike the student-facing chat endpoints.
    Image metadata (id + mime, never bytes) is attached for thumbnail rendering.
    """
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.turn, Message.id)
    )
    messages = db.execute(stmt).scalars().all()
    images_by_message = _images_by_message(db, [m.id for m in messages])
    return [
        {
            "turn": m.turn,
            "role": m.role,
            "content": m.content,
            "pedagogical_reasoning": m.pedagogical_reasoning,
            "images": images_by_message.get(m.id, []),
        }
        for m in messages
    ]


def get_image(db: Session, image_id: int) -> UploadedImage | None:
    """Fetch one uploaded image by id (no ownership check — review sees all)."""
    return db.get(UploadedImage, image_id)


# --- internals ---------------------------------------------------------------


def _order_by(sort: str):
    """ORDER BY clause for the conversation list, by sort mode."""
    recent = Conversation.last_active_at.desc()
    if sort == "student":
        # Named students first (username NULLs last), then most-recent within each.
        return (Conversation.username.is_(None), Conversation.username.asc(), recent)
    return (recent,)


def _message_counts(db: Session, conversation_ids: list[UUID]) -> dict[UUID, int]:
    """Map conversation_id -> total message count (one grouped query)."""
    if not conversation_ids:
        return {}
    stmt = (
        select(Message.conversation_id, func.count(Message.id))
        .where(Message.conversation_id.in_(conversation_ids))
        .group_by(Message.conversation_id)
    )
    return {cid: int(n) for cid, n in db.execute(stmt).all()}


def _last_message_snippets(
    db: Session, conversation_ids: list[UUID]
) -> dict[UUID, str]:
    """Map conversation_id -> short snippet of its latest message.

    Two queries (latest-id per conversation, then those rows' content) instead of
    one per conversation, so the list view avoids N+1.
    """
    if not conversation_ids:
        return {}
    latest_ids_stmt = (
        select(func.max(Message.id))
        .where(Message.conversation_id.in_(conversation_ids))
        .group_by(Message.conversation_id)
    )
    latest_ids = [row[0] for row in db.execute(latest_ids_stmt).all()]
    if not latest_ids:
        return {}
    rows = db.execute(
        select(Message.conversation_id, Message.content).where(
            Message.id.in_(latest_ids)
        )
    ).all()
    out: dict[UUID, str] = {}
    for cid, content in rows:
        text = (content or "").strip()
        out[cid] = (text[:80].rstrip() + "…") if len(text) > 80 else text
    return out


def _summarize(
    c: Conversation,
    counts: dict[UUID, int],
    snippets: dict[UUID, str],
) -> dict:
    """Build the list-view summary dict for one conversation from prefetched maps."""
    return {
        "id": str(c.id),
        "email": c.username,
        "session_id": c.session_id,
        "course": c.course,
        "course_name": course_display_name(c.course),
        "exercise_number": c.exercise_number,
        "tutor_prompt": c.tutor_prompt,
        "started_at": c.started_at.isoformat() if c.started_at else None,
        "last_active_at": c.last_active_at.isoformat() if c.last_active_at else None,
        "message_count": counts.get(c.id, 0),
        "last_message_snippet": snippets.get(c.id),
    }


def _images_by_message(db: Session, message_ids: list[int]) -> dict[int, list[dict]]:
    """Map message_id -> [{"id", "mime_type"}, ...] (one grouped query, no bytes)."""
    if not message_ids:
        return {}
    stmt = (
        select(UploadedImage.id, UploadedImage.message_id, UploadedImage.mime_type)
        .where(UploadedImage.message_id.in_(message_ids))
        .order_by(UploadedImage.id)
    )
    out: dict[int, list[dict]] = {}
    for img_id, msg_id, mime in db.execute(stmt).all():
        out.setdefault(msg_id, []).append({"id": img_id, "mime_type": mime})
    return out
