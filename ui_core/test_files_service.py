import uuid

from sqlalchemy import Text, Uuid
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
)

from ui_core.db.models_common import (
    MessageMixin,
    UploadedFileMixin,
    UploadedImageMixin,
)
from ui_core.db.session import build_engine
from ui_core.services import files as F


def test_read_and_validate_skips_empty(monkeypatch):
    class FS:
        def __init__(self, name, data):
            self.filename = name
            self._data = data
        def read(self):
            return self._data
    out = F.read_and_validate([FS("", b""), FS("t.csv", b"a,b\n1,2\n")])
    assert len(out) == 1 and out[0].kind == "csv"


def test_files_to_text_labels():
    from utils.attachments import validate_files
    atts = validate_files([("t.csv", b"a,b\n1,2\n")])
    assert "[Attachment: t.csv]" in F.files_to_text(atts)


class _Base(DeclarativeBase):
    pass


# Names must match the mixins' string-based relationship targets ("Conversation")
# — this Base has its own registry, so there's no clash with the real app models.
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


class UploadedImage(UploadedImageMixin, _Base):
    """Declared so MessageMixin.uploaded_images resolves; unused here."""


class UploadedFile(UploadedFileMixin, _Base):
    pass


def test_get_file_for_viewer_ownership(tmp_path):
    """get_file_for_viewer returns the row only for an owner (session_id OR username)."""
    eng = build_engine(f"sqlite:///{tmp_path / 'files.db'}", sqlite_fk=True)
    _Base.metadata.create_all(eng)
    try:
        with Session(eng) as s:
            convo = Conversation(session_id="sessA", username="alice")
            s.add(convo)
            s.flush()
            msg = Message(
                conversation_id=convo.id, turn=1, role="student", content="hi"
            )
            s.add(msg)
            s.flush()
            row = UploadedFile(
                message_id=msg.id,
                filename="data.csv",
                kind="csv",
                extracted_text="a,b\n1,2",
                size_bytes=7,
                data=b"a,b\n1,2",
            )
            s.add(row)
            s.commit()

            common = dict(
                uploaded_file_cls=UploadedFile,
                message_cls=Message,
                conversation_cls=Conversation,
            )
            # same session -> owner
            assert F.get_file_for_viewer(s, row.id, "sessA", None, **common) is not None
            # different session but matching username -> owner
            assert F.get_file_for_viewer(s, row.id, "other", "alice", **common) is not None
            # neither -> denied
            assert F.get_file_for_viewer(s, row.id, "other", "bob", **common) is None
            # a username of None must never match a conversation whose username is None
            anon = Conversation(session_id="sessB", username=None)
            s.add(anon)
            s.flush()
            amsg = Message(
                conversation_id=anon.id, turn=1, role="student", content="hi"
            )
            s.add(amsg)
            s.flush()
            arow = UploadedFile(
                message_id=amsg.id,
                filename="x.csv",
                kind="csv",
                extracted_text="",
                size_bytes=0,
                data=b"",
            )
            s.add(arow)
            s.commit()
            assert F.get_file_for_viewer(s, arow.id, "other", None, **common) is None
            # missing id -> None
            assert F.get_file_for_viewer(s, 999999, "sessA", "alice", **common) is None
    finally:
        eng.dispose()
