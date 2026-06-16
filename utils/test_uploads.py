"""Standalone tests for utils.uploads (no pytest dependency).

Run with:
    python -m utils.test_uploads
"""

from __future__ import annotations

from utils.uploads import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES_PER_MESSAGE,
    UploadValidationError,
    images_to_tuples,
    validate_image,
    validate_images,
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
_JPEG = b"\xff\xd8\xff" + b"\x00" * 32

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def _raises(fn) -> bool:
    try:
        fn()
        return False
    except UploadValidationError:
        return True


def test_accepts_png_and_jpeg_by_magic_bytes() -> None:
    png = validate_image("a.png", "image/png", _PNG)
    _check("png sniffed to image/png", png.mime_type == "image/png")
    # Declared MIME is ignored; magic bytes win.
    jpg = validate_image("photo.jpg", "application/octet-stream", _JPEG)
    _check("jpeg sniffed despite bad declared mime", jpg.mime_type == "image/jpeg")
    _check("size_bytes reported", jpg.size_bytes == len(_JPEG))


def test_rejects_empty_oversized_and_non_image() -> None:
    _check("empty rejected", _raises(lambda: validate_image("e.png", "image/png", b"")))
    big = _PNG + b"\x00" * (MAX_IMAGE_BYTES + 1)
    _check("oversized rejected", _raises(lambda: validate_image("big.png", "image/png", big)))
    _check("non-image (gif) rejected", _raises(lambda: validate_image("x.gif", "image/gif", b"GIF89a....")))
    _check("text masquerading as png rejected", _raises(lambda: validate_image("x.png", "image/png", b"not an image")))


def test_count_cap() -> None:
    ok = validate_images([("a.png", "image/png", _PNG)] * MAX_IMAGES_PER_MESSAGE)
    _check("exactly max allowed", len(ok) == MAX_IMAGES_PER_MESSAGE)
    too_many = [("a.png", "image/png", _PNG)] * (MAX_IMAGES_PER_MESSAGE + 1)
    _check("over cap rejected", _raises(lambda: validate_images(too_many)))
    _check("empty list ok (text-only)", validate_images([]) == [])


def test_images_to_tuples() -> None:
    imgs = validate_images([("a.png", "image/png", _PNG), ("b.jpg", "image/jpeg", _JPEG)])
    tuples = images_to_tuples(imgs)
    _check(
        "tuples shape (bytes, mime)",
        tuples == [(_PNG, "image/png"), (_JPEG, "image/jpeg")],
        f"got {[(len(d), m) for d, m in tuples]}",
    )


def main() -> int:
    for t in (
        test_accepts_png_and_jpeg_by_magic_bytes,
        test_rejects_empty_oversized_and_non_image,
        test_count_cap,
        test_images_to_tuples,
    ):
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
