"""SQLAlchemy 2.x models for main_ui.

``Message``, ``Student``, and ``UploadedImage`` are schema-identical across the
web apps and come from the shared mixins in ``ui_core.db.models_common``. Only
``Conversation`` is defined here, on main_ui's own ``Base`` (its schema is the
minimal one; sandbox_ui's adds columns).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, false, Index, Integer, Text, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ui_core.db.models_common import (
    _utcnow,
    FeedbackMixin,
    MessageMixin,
    StudentMixin,
    UploadedFileMixin,
    UploadedImageMixin,
)


class Base(DeclarativeBase):
    """Shared declarative base for all main_ui models."""


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    course: Mapped[str] = mapped_column(Text, nullable=False)
    exercise_number: Mapped[str] = mapped_column(Text, nullable=False)
    # Which content kind exercise_number refers to: "exercise" (graded, default)
    # or "practice". Additive column (server default 'exercise'); legacy rows read
    # back as exercises. Mirrors sandbox_ui's Conversation.exercise_kind.
    exercise_kind: Mapped[str] = mapped_column(
        Text, nullable=False, default="exercise", server_default="exercise"
    )
    # Optional focus: the one sub-problem (Practice Problem N / Graded Assignment
    # N header) in exercise_number's file the student is working on. NULL = no
    # focus (whole file, today's behavior). Set at conversation creation and
    # replayed on later turns (mid-switch defense, like exercise_kind).
    focus_problem: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tutor_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("idx_conversations_username", "username"),
        Index("idx_conversations_session_id", "session_id"),
    )


class Message(MessageMixin, Base):
    # Cached-history mode: JSON string of the RAG records retrieved for this
    # (tutor) turn, so past RAG can be replayed as a system message. NULL for
    # pre-feature rows and turns where no retrieval ran.
    retrieved_context: Mapped[str | None] = mapped_column(Text, nullable=True)


class Student(StudentMixin, Base):
    pass


class UploadedImage(UploadedImageMixin, Base):
    pass


class UploadedFile(UploadedFileMixin, Base):
    pass


class Feedback(FeedbackMixin, Base):
    pass


class ServiceHealth(Base):
    """Single-row (id=1) coordination record for automatic outage detection.

    Read/written across the ~4 gunicorn workers (there is no Redis; Postgres is
    the only shared store), so the runtime "AskTIM is down" banner can engage
    from real ``/api/chat`` traffic instead of a startup-only env flag. See
    ``main_ui/services/service_health.py`` for the state machine; the migration
    seeds the single row.
    """

    __tablename__ = "service_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    degraded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    degraded_since: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_failure_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
