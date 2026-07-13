"""SQLAlchemy 2.x models for sandbox_ui.

``Message``, ``Student``, and ``UploadedImage`` are schema-identical across the
web apps and come from the shared mixins in ``ui_core.db.models_common``. Only
``Conversation`` is defined here, on sandbox_ui's own ``Base`` — it carries
sandbox-only columns (exercise_kind, *_enabled toggles, context_mode) that
main_ui's does not.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Text, Uuid
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
    """Shared declarative base for all sandbox_ui models."""


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    course: Mapped[str] = mapped_column(Text, nullable=False)
    exercise_number: Mapped[str] = mapped_column(Text, nullable=False)
    # sandbox_ui-only: which content kind this conversation's exercise_number
    # refers to — "exercise" (graded, default) or "practice". create_all can't
    # add this to a pre-existing table, but _reconcile_columns() in run_app does.
    # Legacy rows read back NULL and are treated as "exercise" on read.
    exercise_kind: Mapped[str] = mapped_column(
        Text, nullable=False, default="exercise"
    )
    tutor_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    # sandbox_ui-only: whether the course course.txt description was folded into
    # the tutor context for this conversation (toggled via the Create-context
    # wizard, "No course description" option). create_all can't add this to a
    # pre-existing table, but _reconcile_columns() in run_app does.
    course_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    # sandbox_ui-only: whether the course syllabus.txt was folded into the tutor
    # context for this conversation (toggled via the Edit-context switcher).
    syllabus_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    # sandbox_ui-only: whether the course lectures/*.txt transcripts were folded
    # into the tutor context (toggled via the Create-context wizard "Lectures"
    # step). Defaults ON; _reconcile_columns() in run_app backfills it.
    lectures_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    # sandbox_ui-only: per-conversation context mode chosen via the Create-context
    # wizard's RAG toggle ("rag" | "full_context"). NULL = resolve by default
    # (rag when the course has an index, else full_context). create_all can't add
    # this to a pre-existing table, but _reconcile_columns() in run_app does.
    context_mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    # sandbox_ui-only: per-conversation tutor LLM provider chosen via the
    # Create-context wizard's tutor step ("claude" | "gpt"). NULL = server default
    # (claude / Sonnet 5). create_all can't add this to a pre-existing table, but
    # _reconcile_columns() in run_app does.
    provider: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    # sandbox_ui-only: JSON string of the RAG chunks retrieved for this (tutor)
    # turn — a list of ``{source, score, chars, text}``. NULL for non-RAG turns
    # and legacy rows. create_all can't add this to a pre-existing table, but
    # _reconcile_columns() in run_app backfills it on boot.
    retrieved_context: Mapped[str | None] = mapped_column(Text, nullable=True)


class Student(StudentMixin, Base):
    pass


class UploadedImage(UploadedImageMixin, Base):
    pass


class UploadedFile(UploadedFileMixin, Base):
    pass


class Feedback(FeedbackMixin, Base):
    pass
