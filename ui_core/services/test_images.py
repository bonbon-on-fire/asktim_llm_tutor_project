"""Standalone tests for ui_core.services.images (no pytest).

Run with:
    python -m ui_core.services.test_images

The helpers are model-agnostic — they take the ORM classes as arguments — so
they're tested in ISOLATION on a local Base (ui_core must not depend on the app
packages). A minimal Conversation supplies the ownership columns + back-ref.
"""

from __future__ import annotations

import io
import tempfile
import uuid
from pathlib import Path

from sqlalchemy import Text, Uuid
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
)
from werkzeug.datastructures import FileStorage

from ui_core.db.models_common import (
    MessageMixin,
    StudentMixin,
    UploadedFileMixin,
    UploadedImageMixin,
)
from ui_core.db.session import build_engine
from ui_core.services import images as svc
from utils.uploads import ValidatedImage

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
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    """Not exercised by these tests; declared so MessageMixin.uploaded_files resolves."""


def _img(name: str, data: bytes = b"abc") -> ValidatedImage:
    """Build a ``ValidatedImage`` PNG test fixture with the given name and bytes."""
    return ValidatedImage(filename=name, mime_type="image/png", data=data)


def test_read_and_validate_skips_empty() -> None:
    """Check ``read_and_validate`` returns ``[]`` for empty input and skips filename-less uploads."""
    _check("empty list -> []", svc.read_and_validate([]) == [])
    # a FileStorage with no filename is skipped before validation
    fs = FileStorage(stream=io.BytesIO(b""), filename="")
    _check("filename-less upload skipped", svc.read_and_validate([fs]) == [])


def test_persist_and_ownership() -> None:
    """Check ``persist_images`` writes rows and ``get_image_for_viewer`` enforces ownership."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        eng = build_engine(f"sqlite:///{Path(tmp) / 'img.db'}", sqlite_fk=True)
        _Base.metadata.create_all(eng)
        with Session(eng) as s:
            convo = Conversation(session_id="sessA", username="alice")
            s.add(convo)
            s.flush()
            msg = Message(conversation_id=convo.id, turn=1, role="student", content="hi")
            s.add(msg)
            s.flush()

            rows = svc.persist_images(
                s,
                message=msg,
                images=[_img("a.png"), _img("b.png", b"defgh")],
                uploaded_image_cls=UploadedImage,
            )
            s.commit()
            _check("persist returns 2 rows", len(rows) == 2)
            _check("row fields set", rows[0].filename == "a.png" and rows[0].size_bytes == 3)
            _check("second row size", rows[1].size_bytes == 5)

            iid = rows[0].id
            common = dict(
                uploaded_image_cls=UploadedImage,
                message_cls=Message,
                conversation_cls=Conversation,
            )
            # same session -> owner
            _check(
                "owner by session_id",
                svc.get_image_for_viewer(s, iid, "sessA", None, **common) is not None,
            )
            # different session but matching username -> owner
            _check(
                "owner by username",
                svc.get_image_for_viewer(s, iid, "other", "alice", **common) is not None,
            )
            # neither -> denied
            _check(
                "stranger denied",
                svc.get_image_for_viewer(s, iid, "other", "bob", **common) is None,
            )
            # missing id -> None
            _check(
                "missing id -> None",
                svc.get_image_for_viewer(s, 999999, "sessA", "alice", **common) is None,
            )
        eng.dispose()


def main() -> int:
    """Run all tests in this module and return an exit code (1 if any failed)."""
    for t in (test_read_and_validate_skips_empty, test_persist_and_ownership):
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
