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
from ui_core.usage import model_from_usage_json, records_from_retrieved_context


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
    costs = _total_costs(db, ids)
    return [_summarize(c, counts, snippets, costs) for c in convos]


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
    return [_message_dict(m, images_by_message) for m in messages]


def _message_dict(m: Message, images_by_message: dict[int, list[dict]]) -> dict:
    """One message as a JSON-friendly dict for the transcript view.

    Beyond the base fields, tutor rows carry the review metadata the sandbox
    surfaces: the per-message thumb ``rating`` (-1/0/1), the turn's estimated
    ``cost_usd`` with the ``model`` id parsed out of ``usage_json``, and the
    ``retrieved`` RAG chunks parsed from ``retrieved_context``.
    """
    entry = {
        "turn": m.turn,
        "role": m.role,
        "content": m.content,
        "pedagogical_reasoning": m.pedagogical_reasoning,
        # Per-message thumb (-1/0/1); legacy rows read back NULL -> 0.
        "rating": getattr(m, "rating", 0) or 0,
        "images": images_by_message.get(m.id, []),
    }
    cost = getattr(m, "cost_usd", None)
    if cost is not None:
        entry["cost_usd"] = cost
        # Model id lives inside the stored breakdown; parse it out so the UI can
        # render "model ($cost)". Absent/corrupt JSON -> None.
        entry["model"] = model_from_usage_json(getattr(m, "usage_json", None))
    retrieved = records_from_retrieved_context(getattr(m, "retrieved_context", None))
    if retrieved:
        entry["retrieved"] = retrieved
    return entry


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


def _total_costs(db: Session, conversation_ids: list[UUID]) -> dict[UUID, float]:
    """Map conversation_id -> summed tutor ``cost_usd`` (one grouped query).

    NULL costs (student rows, pre-feature rows) coalesce to 0, so a conversation
    with no tracked cost sums to 0.0.
    """
    if not conversation_ids:
        return {}
    stmt = (
        select(
            Message.conversation_id,
            func.coalesce(func.sum(Message.cost_usd), 0.0),
        )
        .where(Message.conversation_id.in_(conversation_ids))
        .group_by(Message.conversation_id)
    )
    return {cid: float(total or 0.0) for cid, total in db.execute(stmt).all()}


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
    costs: dict[UUID, float],
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
        "total_cost_usd": costs.get(c.id, 0.0),
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
