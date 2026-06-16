"""Shared validation for student-uploaded images.

Both `main_ui` and `test_ui` accept per-message image uploads in their chat
composers. The Flask file-parsing differs per app, but the actual rules — which
MIME types, how big, how many — are identical and live here so the two apps
can't drift. Pure functions over ``(filename, mime, bytes)``; no Flask, no DB.
"""

from __future__ import annotations

from dataclasses import dataclass

# PNG / JPEG only (matches the curriculum figure convention). No GIF/SVG/PDF.
ALLOWED_IMAGE_MIMES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
}

# Per-file and per-message caps. Kept conservative so a single chat turn can't
# push a huge multimodal payload at the model or bloat the Postgres row.
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_IMAGES_PER_MESSAGE = 5

# Magic-byte signatures so we don't trust the client-declared MIME blindly.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC = b"\xff\xd8\xff"


class UploadValidationError(ValueError):
    """Raised when an uploaded image fails validation (bad type, too big, too many)."""


@dataclass(frozen=True)
class ValidatedImage:
    """A single accepted upload: original filename, normalized MIME, raw bytes."""

    filename: str
    mime_type: str
    data: bytes

    @property
    def size_bytes(self) -> int:
        return len(self.data)


def _sniff_mime(data: bytes) -> str | None:
    """Return the MIME type implied by the leading magic bytes, or None."""
    if data.startswith(_PNG_MAGIC):
        return "image/png"
    if data.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    return None


def validate_image(filename: str, declared_mime: str | None, data: bytes) -> ValidatedImage:
    """Validate one upload and return a normalized :class:`ValidatedImage`.

    The MIME is taken from the file's magic bytes (not the client-declared
    value) and must be PNG or JPEG. Empty or oversized files are rejected.
    """
    if not data:
        raise UploadValidationError(f"'{filename}' is empty.")
    if len(data) > MAX_IMAGE_BYTES:
        raise UploadValidationError(
            f"'{filename}' is {len(data)} bytes; max is {MAX_IMAGE_BYTES} bytes."
        )
    sniffed = _sniff_mime(data)
    if sniffed is None:
        raise UploadValidationError(
            f"'{filename}' is not a PNG or JPEG image."
        )
    return ValidatedImage(filename=filename or f"upload{ALLOWED_IMAGE_MIMES[sniffed]}", mime_type=sniffed, data=data)


def validate_images(items: list[tuple[str, str | None, bytes]]) -> list[ValidatedImage]:
    """Validate a list of ``(filename, declared_mime, data)`` uploads.

    Enforces the per-message count cap and validates each file. Raises
    :class:`UploadValidationError` on the first problem. An empty list is
    valid (a text-only turn) and returns ``[]``.
    """
    if len(items) > MAX_IMAGES_PER_MESSAGE:
        raise UploadValidationError(
            f"Too many images: {len(items)} (max {MAX_IMAGES_PER_MESSAGE} per message)."
        )
    return [validate_image(name, mime, data) for (name, mime, data) in items]


def images_to_tuples(images: list[ValidatedImage]) -> list[tuple[bytes, str]]:
    """Convert validated images to ``(bytes, mime)`` tuples for multimodal content."""
    return [(img.data, img.mime_type) for img in images]
