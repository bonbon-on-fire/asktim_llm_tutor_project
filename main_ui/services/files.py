"""main_ui binding of the shared file-upload service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from main_ui.db.models import Conversation, Message, UploadedFile
from ui_core.services import files as _shared
from utils.attachments import ValidatedAttachment

read_and_validate = _shared.read_and_validate
files_to_text = _shared.files_to_text


def persist_files(db: Session, *, message, files: list[ValidatedAttachment]):
    """Insert one UploadedFile row per attachment, linked to *message*."""
    return _shared.persist_files(db, message=message, files=files, uploaded_file_cls=UploadedFile)


def get_file_for_viewer(
    db: Session,
    file_id: int,
    session_id: str,
    username: str | None,
) -> UploadedFile | None:
    """Return an `UploadedFile` if the viewer owns the parent conversation."""
    return _shared.get_file_for_viewer(
        db,
        file_id,
        session_id,
        username,
        uploaded_file_cls=UploadedFile,
        message_cls=Message,
        conversation_cls=Conversation,
    )
