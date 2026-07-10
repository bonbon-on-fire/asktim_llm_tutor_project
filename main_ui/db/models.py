"""SQLAlchemy 2.x models for main_ui.

``Message``, ``Student``, and ``UploadedImage`` are schema-identical across the
web apps and come from the shared mixins in ``ui_core.db.models_common``. Only
``Conversation`` is defined here, on main_ui's own ``Base`` (its schema is the
minimal one; sandbox_ui's adds columns).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, Text, Uuid
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
    pass


class Student(StudentMixin, Base):
    pass


class UploadedImage(UploadedImageMixin, Base):
    pass


class UploadedFile(UploadedFileMixin, Base):
    pass


class Feedback(FeedbackMixin, Base):
    pass
