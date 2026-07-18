"""Minimal read-only SQLAlchemy models for database_ui.

These deliberately map ONLY the columns common to both the ``main_ui`` and
``sandbox_ui`` ``conversations`` schemas. ``sandbox_ui`` carries extra columns
(``lectures_enabled``, ``context_mode``, ``provider``) that ``main_ui`` lacks;
mapping them here would make the same model crash when pointed at the main DB.
By selecting only the shared columns, one model reads both databases unchanged.

Read-only: this app never inserts, updates, or creates these tables. The schema
is owned by the live apps (``main_ui`` / ``sandbox_ui``); we only SELECT.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# Matches the live apps: BigInteger PKs on Postgres, Integer on SQLite (local).
_BigIntPk = BigInteger().with_variant(Integer(), "sqlite")


class Base(DeclarativeBase):
    """Declarative base for database_ui's read-only models."""


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
    course: Mapped[str] = mapped_column(Text, nullable=False)
    exercise_number: Mapped[str] = mapped_column(Text, nullable=False)
    tutor_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_active_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", viewonly=True
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(_BigIntPk, primary_key=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("conversations.id"), nullable=False
    )
    turn: Mapped[int] = mapped_column(nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    pedagogical_reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-message thumb rating from the student: -1 (down), 0 (none), 1 (up).
    # Only ever set on tutor rows. Shared across both schemas (MessageMixin), so
    # safe to SELECT whether pointed at main_ui or sandbox_ui.
    rating: Mapped[int] = mapped_column(nullable=False, server_default="0", default=0)
    # Estimated USD cost of producing this (tutor) turn; NULL on student rows and
    # rows created before cost tracking. Shared across both schemas.
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    # JSON breakdown backing ``cost_usd`` (model id + token counts). The model id
    # is parsed out for the per-message model label. NULL when ``cost_usd`` is.
    usage_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON string of the RAG chunks retrieved for this (tutor) turn — a list of
    # ``{source, score, chars, text}``. NULL for non-RAG turns. Present in both
    # schemas (main_ui caches it for history replay; sandbox_ui for review).
    retrieved_context: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    conversation: Mapped["Conversation"] = relationship(
        back_populates="messages", viewonly=True
    )
    uploaded_images: Mapped[list["UploadedImage"]] = relationship(
        back_populates="message", viewonly=True
    )


class UploadedImage(Base):
    __tablename__ = "uploaded_images"

    id: Mapped[int] = mapped_column(_BigIntPk, primary_key=True)
    message_id: Mapped[int] = mapped_column(
        _BigIntPk, ForeignKey("messages.id"), nullable=False
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    message: Mapped["Message"] = relationship(
        back_populates="uploaded_images", viewonly=True
    )
