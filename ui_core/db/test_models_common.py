"""Standalone tests for ui_core.db.models_common mixins (no pytest).

Run with:
    python -m ui_core.db.test_models_common

The mixins are tested in ISOLATION on a local Base — ui_core must not depend on
the app packages. A minimal local Conversation provides the FK target and the
back-populated relationship that the Message / UploadedImage / UploadedFile
mixins expect.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from sqlalchemy import Uuid
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
)

from ui_core.db.session import build_engine
from ui_core.db.models_common import (
    MessageMixin,
    StudentMixin,
    UploadedFileMixin,
    UploadedImageMixin,
)

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    """Record and print a PASS/FAIL for *name* based on *condition*."""
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


class _Base(DeclarativeBase):
    pass


class Conversation(_Base):
    """Minimal FK target + back-ref for the Message mixin's relationship."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Message(MessageMixin, _Base):
    pass


class Student(StudentMixin, _Base):
    pass


class UploadedImage(UploadedImageMixin, _Base):
    pass


class UploadedFile(UploadedFileMixin, _Base):
    pass


def test_tablenames() -> None:
    """Verify each mixin-derived model maps to its expected table name."""
    _check("message tablename", Message.__tablename__ == "messages")
    _check("student tablename", Student.__tablename__ == "students")
    _check("uploaded_image tablename", UploadedImage.__tablename__ == "uploaded_images")
    _check("uploaded_file tablename", UploadedFile.__tablename__ == "uploaded_files")


def test_mixins_map_and_roundtrip() -> None:
    """Create the tables on SQLite and round-trip rows to check columns and relationships."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        eng = build_engine(f"sqlite:///{Path(tmp) / 'm.db'}", sqlite_fk=True)
        _Base.metadata.create_all(eng)
        with Session(eng) as s:
            c = Conversation()
            s.add(c)
            s.flush()
            msg = Message(conversation_id=c.id, turn=1, role="student", content="hi")
            s.add(msg)
            s.flush()
            s.add(
                UploadedImage(
                    message_id=msg.id, filename="a.png", mime_type="image/png",
                    size_bytes=3, data=b"abc",
                )
            )
            s.add(
                UploadedFile(
                    message_id=msg.id, filename="a.csv", kind="csv",
                    extracted_text="a,b\n1,2", size_bytes=8, data=b"a,b\n1,2",
                )
            )
            s.add(Student(username="u", password_hash="h"))
            s.commit()

            m2 = s.get(Message, msg.id)
            _check("message.conversation resolves", m2.conversation.id == c.id)
            _check("message.uploaded_images", [i.filename for i in m2.uploaded_images] == ["a.png"])
            _check("message.uploaded_files", [f.filename for f in m2.uploaded_files] == ["a.csv"])
            _check("conversation.messages", [x.id for x in c.messages] == [msg.id])
            _check("uploaded_image.message", s.get(UploadedImage, 1).message.id == msg.id)
            _check("uploaded_file.message", s.get(UploadedFile, 1).message.id == msg.id)
            _check("student round-trips", s.get(Student, "u").password_hash == "h")
        eng.dispose()


def main() -> int:
    """Run all tests in this module and return an exit code (1 if any failed)."""
    for t in (test_tablenames, test_mixins_map_and_roundtrip):
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
