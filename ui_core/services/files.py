"""Shared student file-upload helpers (non-image attachments).

Mirrors ``ui_core.services.images``: bridges Flask uploads to the pure
validation/extraction in ``utils.attachments``, persists accepted files as
``UploadedFile`` rows (bytes + extracted text in-DB). Model class passed in so
this stays app-agnostic.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session
from werkzeug.datastructures import FileStorage

from utils.attachments import (
    ValidatedAttachment,
    attachments_to_text_block,
    validate_files,
)


def read_and_validate(files: list[FileStorage]) -> list[ValidatedAttachment]:
    """Read Flask uploads into validated attachments (type + size + budget)."""
    items: list[tuple[str, bytes]] = []
    for fs in files:
        if fs is None or not fs.filename:
            continue
        items.append((fs.filename, fs.read()))
    return validate_files(items)


def persist_files(
    db: Session,
    *,
    message: Any,
    files: list[ValidatedAttachment],
    uploaded_file_cls: type,
) -> list[Any]:
    """Insert one ``UploadedFile`` row per validated attachment, linked to *message*."""
    rows: list[Any] = []
    for att in files:
        row = uploaded_file_cls(
            message_id=message.id,
            filename=att.filename,
            kind=att.kind,
            extracted_text=att.extracted_text,
            size_bytes=att.size_bytes,
            data=att.data,
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def files_to_text(files: list[ValidatedAttachment]) -> str:
    """Render attachments as labeled text blocks for the tutor message."""
    return attachments_to_text_block(files)
