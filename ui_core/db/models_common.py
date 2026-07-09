"""Shared SQLAlchemy column mixins for the web apps' models.

``Message``, ``Student``, and ``UploadedImage`` are schema-identical across
``main_ui`` and ``sandbox_ui``, so their column / relationship definitions live
here as declarative mixins. Each app still declares the concrete class on its
OWN ``Base`` — keeping the table in that app's ``metadata`` for Alembic /
``create_all`` — e.g.::

    class Message(MessageMixin, Base):
        pass

``Conversation`` is NOT shared: its schema diverges (sandbox adds columns), so
each app keeps its own ``Conversation`` class. ``_utcnow`` and ``_BigIntPk`` are
shared here because every model (including the per-app ``Conversation``) uses
them.
"""

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
    LargeBinary,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship


# SQLite only auto-increments columns typed exactly INTEGER PRIMARY KEY.
# Use BigInteger on real backends (Postgres) and fall back to Integer on SQLite
# so autoincrement works in local dev.
_BigIntPk = BigInteger().with_variant(Integer(), "sqlite")


def _utcnow() -> datetime:
    """tz-aware UTC datetime; used as a Python-side default for timestamp columns."""
    return datetime.now(timezone.utc)


class StudentMixin:
    """Soft-identity record: one row per username that's been linked to a password.

    Not a real auth system — just a proof-of-ownership check that prevents
    casual impersonation when a student claims an existing username from a new
    browser. The ``username`` cookie remains the active session-identity carrier;
    this row exists so we can verify the claim on first link.
    """

    __tablename__ = "students"

    username: Mapped[str] = mapped_column(Text, primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


class MessageMixin:
    """Columns + relationships for the ``messages`` table."""

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

    @declared_attr
    def conversation(cls) -> Mapped["Conversation"]:  # noqa: F821 - resolved per app
        """Relationship to the owning ``Conversation`` (back-populates ``messages``)."""
        return relationship(back_populates="messages")

    @declared_attr
    def uploaded_images(cls) -> Mapped[list["UploadedImage"]]:  # noqa: F821
        """Relationship to this message's ``UploadedImage`` rows (delete-orphan cascade)."""
        return relationship(
            back_populates="message",
            cascade="all, delete-orphan",
            passive_deletes=True,
        )

    @declared_attr
    def uploaded_files(cls) -> Mapped[list["UploadedFile"]]:  # noqa: F821
        """Non-image attachments on this message (back-populates ``message``)."""
        return relationship(
            back_populates="message",
            cascade="all, delete-orphan",
            passive_deletes=True,
        )

    @declared_attr.directive
    def __table_args__(cls):
        """Table-level constraints: a role check and an index on ``conversation_id``."""
        return (
            CheckConstraint("role IN ('student', 'tutor')", name="ck_messages_role"),
            Index("idx_messages_conversation", "conversation_id"),
        )


class UploadedImageMixin:
    """Columns + relationship for the ``uploaded_images`` table."""

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
    # Raw image bytes. Stored in-DB (BYTEA on Postgres) rather than on disk
    # because Railway's filesystem is ephemeral — disk uploads would vanish on
    # every redeploy. Durable here and re-servable via GET /api/image/<id>.
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    @declared_attr
    def message(cls) -> Mapped["Message"]:  # noqa: F821 - resolved per app
        """Relationship to the owning ``Message`` (back-populates ``uploaded_images``)."""
        return relationship(back_populates="uploaded_images")

    @declared_attr.directive
    def __table_args__(cls):
        """Table-level args: an index on ``message_id``."""
        return (Index("idx_uploaded_images_message", "message_id"),)


class UploadedFileMixin:
    """Columns + relationship for the ``uploaded_files`` table (non-image attachments)."""

    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(_BigIntPk, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        _BigIntPk,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # Plain text extracted at upload time — this is what reaches the tutor and is
    # re-injected into history every turn (persist-across-turns).
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    # Raw file bytes, stored in-DB like uploaded_images (Railway FS is ephemeral).
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    @declared_attr
    def message(cls) -> Mapped["Message"]:  # noqa: F821 - resolved per app
        """Relationship to the owning ``Message`` (back-populates ``uploaded_files``)."""
        return relationship(back_populates="uploaded_files")

    @declared_attr.directive
    def __table_args__(cls):
        """Table-level args: an index on ``message_id``."""
        return (Index("idx_uploaded_files_message", "message_id"),)
