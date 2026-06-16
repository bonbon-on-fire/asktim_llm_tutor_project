"""Student image-upload helpers for main_ui.

Bridges Flask's uploaded files to the shared validation in
:mod:`utils.uploads`, persists accepted images as `UploadedImage` rows (bytes
stored in-DB), and serves them back with an ownership check. Route handlers
call these; they never build `UploadedImage` inline.
"""

from __future__ import annotations

from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage

from main_ui.db.models import Conversation, Message, UploadedImage
from utils.uploads import ValidatedImage, validate_images


def read_and_validate(files: list[FileStorage]) -> list[ValidatedImage]:
    """Read Flask uploads into validated images (PNG/JPEG, size + count caps).

    Raises ``utils.uploads.UploadValidationError`` on the first bad file.
    """
    items: list[tuple[str, str | None, bytes]] = []
    for fs in files:
        if fs is None or not fs.filename:
            continue
        items.append((fs.filename, fs.mimetype, fs.read()))
    return validate_images(items)


def persist_images(
    db: Session,
    *,
    message: Message,
    images: list[ValidatedImage],
) -> list[UploadedImage]:
    """Insert one `UploadedImage` row per validated image, linked to *message*."""
    rows: list[UploadedImage] = []
    for img in images:
        row = UploadedImage(
            message_id=message.id,
            filename=img.filename,
            mime_type=img.mime_type,
            size_bytes=img.size_bytes,
            data=img.data,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def get_image_for_viewer(
    db: Session,
    image_id: int,
    session_id: str,
    email: str | None,
) -> UploadedImage | None:
    """Return an `UploadedImage` if the viewer owns the parent conversation.

    Ownership = same session_id (same browser) OR matching email
    (cross-browser). Returns ``None`` otherwise so the route can 404 without
    leaking existence.
    """
    img = db.get(UploadedImage, image_id)
    if img is None:
        return None
    message = db.get(Message, img.message_id)
    if message is None:
        return None
    convo = db.get(Conversation, message.conversation_id)
    if convo is None:
        return None
    if convo.session_id == session_id:
        return img
    if email and convo.email == email:
        return img
    return None
