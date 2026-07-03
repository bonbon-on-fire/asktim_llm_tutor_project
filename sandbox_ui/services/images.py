"""Student image-upload helpers for sandbox_ui.

Thin wrapper over :mod:`ui_core.services.images`: binds sandbox_ui's own model
classes (its ``Conversation`` schema differs from main_ui's) to the shared,
app-agnostic logic.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from sandbox_ui.db.models import Conversation, Message, UploadedImage
from ui_core.services import images as _shared
from utils.uploads import ValidatedImage

# Model-free helper — re-exported unchanged.
read_and_validate = _shared.read_and_validate


def persist_images(
    db: Session,
    *,
    message: Message,
    images: list[ValidatedImage],
) -> list[UploadedImage]:
    """Insert one `UploadedImage` row per validated image, linked to *message*."""
    return _shared.persist_images(
        db, message=message, images=images, uploaded_image_cls=UploadedImage
    )


def get_image_for_viewer(
    db: Session,
    image_id: int,
    session_id: str,
    username: str | None,
) -> UploadedImage | None:
    """Return an `UploadedImage` if the viewer owns the parent conversation."""
    return _shared.get_image_for_viewer(
        db,
        image_id,
        session_id,
        username,
        uploaded_image_cls=UploadedImage,
        message_cls=Message,
        conversation_cls=Conversation,
    )
