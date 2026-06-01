"""SQLAlchemy 2.x models for main_ui."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)


# SQLite only auto-increments columns typed exactly INTEGER PRIMARY KEY.
# Use BigInteger on real backends (Postgres) and fall back to Integer on SQLite
# so autoincrement works in local dev.
_BigIntPk = BigInteger().with_variant(Integer(), "sqlite")
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    """tz-aware UTC datetime; used as a Python-side default for timestamp columns."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Shared declarative base for all main_ui models."""


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(Text, nullable=True)
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
        Index("idx_conversations_email", "email"),
        Index("idx_conversations_session_id", "session_id"),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(_BigIntPk, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    turn: Mapped[int] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    pedagogical_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
    uploaded_images: Mapped[list["UploadedImage"]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint("role IN ('student', 'tutor')", name="ck_messages_role"),
        Index("idx_messages_conversation", "conversation_id"),
    )


class Student(Base):
    """Soft-identity record: one row per email that's been linked to a password.

    Not a real auth system — just a proof-of-ownership check that prevents
    casual impersonation when a student claims an existing email from a new
    browser. The `email` cookie remains the active session-identity carrier;
    this row exists so we can verify the claim on first link.
    """

    __tablename__ = "students"

    email: Mapped[str] = mapped_column(Text, primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class UploadedImage(Base):
    __tablename__ = "uploaded_images"

    id: Mapped[int] = mapped_column(_BigIntPk, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        _BigIntPk,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    message: Mapped["Message"] = relationship(back_populates="uploaded_images")

    __table_args__ = (Index("idx_uploaded_images_message", "message_id"),)
