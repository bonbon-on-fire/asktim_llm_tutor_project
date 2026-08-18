# database_ui/analytics/data.py
"""Windowed, scope-filtered read-queries feeding the weekly report.

Returns plain dataclasses (not ORM objects) so the statistics layer is pure and
unit-testable without a database. All filtering is SELECT-only; course scoping
uses the same ``courses is None -> no filter`` idiom as services/conversations.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from database_ui.analytics.weeks import TZ, Week
from database_ui.db.models import Conversation, Message


@dataclass(frozen=True)
class ConvRow:
    id: str
    course: str
    username: str | None
    exercise_number: str
    exercise_kind: str
    focus_problem: int | None
    tutor_prompt: str
    started_at: datetime | None
    last_active_at: datetime | None


@dataclass(frozen=True)
class MsgRow:
    conversation_id: str
    turn: int
    role: str
    content: str
    rating: int
    cost_usd: float | None
    usage_json: str | None
    has_rag: bool
    created_at: datetime | None


def _scoped(stmt, courses: list[str] | None):
    if courses is not None:
        stmt = stmt.where(Conversation.course.in_(courses))
    return stmt


def fetch_conversations(db: Session, week: Week, courses: list[str] | None) -> list[ConvRow]:
    """Conversations whose ``started_at`` falls in ``week`` (UTC half-open)."""
    stmt = _scoped(
        select(Conversation).where(
            Conversation.started_at >= week.start_utc,
            Conversation.started_at < week.end_utc,
        ),
        courses,
    ).order_by(Conversation.started_at.asc())
    return [
        ConvRow(
            id=str(c.id),
            course=c.course,
            username=c.username,
            exercise_number=c.exercise_number,
            exercise_kind=c.exercise_kind,
            focus_problem=c.focus_problem,
            tutor_prompt=c.tutor_prompt,
            started_at=c.started_at,
            last_active_at=c.last_active_at,
        )
        for c in db.execute(stmt).scalars().all()
    ]


def fetch_messages(db: Session, conversation_ids: list[str]) -> list[MsgRow]:
    """All messages for the given conversations, ordered by (conversation, turn)."""
    if not conversation_ids:
        return []
    ids = [uuid.UUID(cid) for cid in conversation_ids]
    stmt = (
        select(Message)
        .where(Message.conversation_id.in_(ids))
        .order_by(Message.conversation_id, Message.turn, Message.id)
    )
    return [
        MsgRow(
            conversation_id=str(m.conversation_id),
            turn=m.turn,
            role=m.role,
            content=m.content,
            rating=m.rating,
            cost_usd=m.cost_usd,
            usage_json=m.usage_json,
            has_rag=bool(m.retrieved_context),
            created_at=m.created_at,
        )
        for m in db.execute(stmt).scalars().all()
    ]


def prior_usernames(db: Session, before: datetime, courses: list[str] | None) -> set[str]:
    """Distinct usernames that appear in any conversation started before ``before``.

    Used to classify a week's students as new vs returning.
    """
    stmt = _scoped(
        select(Conversation.username)
        .where(Conversation.started_at < before, Conversation.username.is_not(None))
        .distinct(),
        courses,
    )
    return {u for (u,) in db.execute(stmt).all() if u}


def distinct_courses(db: Session, courses: list[str] | None) -> list[str]:
    """Sorted distinct course keys present in the data, scoped to ``courses``.

    Feeds the report's course-filter dropdown, so only courses that actually
    have conversations appear as options.
    """
    stmt = _scoped(select(Conversation.course).distinct(), courses)
    return sorted({c for (c,) in db.execute(stmt).all() if c})


def earliest_conversation_date(db: Session, courses: list[str] | None) -> date | None:
    """Local (America/New_York) date of the earliest conversation, scoped.

    Feeds the week picker's lower bound. ``None`` when there is no data at all.
    """
    stmt = _scoped(select(func.min(Conversation.started_at)), courses)
    ts = db.execute(stmt).scalar_one_or_none()
    return ts.astimezone(TZ).date() if ts is not None else None


def fetch_transcript(db: Session, conversation_id: str) -> list[tuple[str, str]]:
    """Ordered ``(role, content)`` pairs for one conversation, for the judge."""
    stmt = (
        select(Message.role, Message.content)
        .where(Message.conversation_id == uuid.UUID(conversation_id))
        .order_by(Message.turn, Message.id)
    )
    return [(role, content) for role, content in db.execute(stmt).all()]
