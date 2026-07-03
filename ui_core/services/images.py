"""Shared student image-upload helpers for the web apps.

Bridges Flask's uploaded files to the shared validation in
:mod:`utils.uploads`, persists accepted images as ``UploadedImage`` rows (bytes
stored in-DB), and serves them back with an ownership check.

The ORM model classes are passed in rather than imported: each app declares its
own ``Conversation`` / ``Message`` / ``UploadedImage`` on its own ``Base`` (the
``Conversation`` schemas diverge), so these helpers stay app-agnostic and each
app binds its own models via a thin wrapper in ``<app>/services/images.py``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage

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
    message: Any,
    images: list[ValidatedImage],
    uploaded_image_cls: type,
) -> list[Any]:
    """Insert one ``UploadedImage`` row per validated image, linked to *message*."""
    rows: list[Any] = []
    for img in images:
        row = uploaded_image_cls(
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
    username: str | None,
    *,
    uploaded_image_cls: type,
    message_cls: type,
    conversation_cls: type,
) -> Any | None:
    """Return an ``UploadedImage`` if the viewer owns the parent conversation.

    Ownership = same session_id (same browser) OR matching username
    (cross-browser). Returns ``None`` otherwise so the route can 404 without
    leaking existence.
    """
    img = db.get(uploaded_image_cls, image_id)
    if img is None:
        return None
    message = db.get(message_cls, img.message_id)
    if message is None:
        return None
    convo = db.get(conversation_cls, message.conversation_id)
    if convo is None:
        return None
    if convo.session_id == session_id:
        return img
    if username and convo.username == username:
        return img
    return None
