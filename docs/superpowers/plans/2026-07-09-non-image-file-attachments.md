# Non-image File Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let students attach CSV/TSV/XLSX/PDF/DOCX/TXT files (not just images) to a tutor message; extract each to text, budget-cap it, and keep it visible to the tutor across turns.

**Architecture:** Mirror the existing image pipeline. A new pure module `utils/attachments.py` validates + extracts files to text. A new `UploadedFile` table (bytes + extracted text) stores them like `UploadedImage`. `get_history_for_tutor` appends each student turn's extracted text to that turn's model-facing content, so files persist across turns while chat bubbles stay clean. Routes read a new `files` multipart field; frontends render chips.

**Tech Stack:** Python 3.12, Flask, SQLAlchemy, Alembic (main_ui only), LangChain, `openpyxl` + `python-docx` (new), `pypdf` (existing RAG dep), stdlib `csv`.

## Global Constraints

- File types: CSV, TSV, XLSX, PDF, DOCX, TXT (extract to text — never native PDF blocks).
- Per-file byte cap: **5 MB** for files; images keep their existing **10 MB** cap.
- Combined attachments per message: **≤ 3** (images + files together).
- Per-message extracted-text budget: **15000 chars** across all files; truncate beyond with `\n[…truncated N chars for length…]`.
- Both `sandbox_ui` and `main_ui` get the feature; shared logic lives in `utils/` and `ui_core/`.
- Attachment text reaches the model as a text block `\n\n[Attachment: <name>]\n<text>`, never as an `image_url` block; it lives only in model-facing history, never in the stored/displayed message `content`.
- Extraction failures return a clean 400, never a 500.
- No new dependency may be imported at module top level of `utils/attachments.py` without a lazy fallback that raises `AttachmentExtractionError` if missing (keeps import-time safe for callers that never touch XLSX/DOCX).

---

### Task 1: `utils/attachments.py` — validation + extraction + budget

**Files:**
- Create: `utils/attachments.py`
- Test: `utils/test_attachments.py`
- Modify: `requirements.txt` (add `openpyxl`, `python-docx`)

**Interfaces:**
- Produces:
  - `ALLOWED_FILE_EXTS: dict[str, str]` — ext → kind (`".csv"`→`"csv"`, `".tsv"`→`"tsv"`, `".xlsx"`→`"xlsx"`, `".pdf"`→`"pdf"`, `".docx"`→`"docx"`, `".txt"`→`"txt"`)
  - `MAX_FILE_BYTES = 5 * 1024 * 1024`
  - `MAX_EXTRACTED_CHARS = 15000`
  - `class AttachmentValidationError(ValueError)`
  - `class AttachmentExtractionError(ValueError)`
  - `class EmptyExtractionError(ValueError)`
  - `@dataclass(frozen=True) ValidatedAttachment(filename: str, kind: str, extracted_text: str, data: bytes)` with `size_bytes` property
  - `validate_file(filename: str, data: bytes) -> ValidatedAttachment` — detect kind, cap bytes, extract; raises on failure
  - `validate_files(items: list[tuple[str, bytes]]) -> list[ValidatedAttachment]` — validate each, then enforce the 15000-char combined budget by truncating the LAST files' text
  - `attachments_to_text_block(atts: list[ValidatedAttachment]) -> str` — join as `\n\n[Attachment: <name>]\n<text>` blocks (empty string if none)

- [ ] **Step 1: Write failing tests**

```python
# utils/test_attachments.py
import io
import pytest
from utils import attachments as A


def _xlsx_bytes(rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _docx_bytes(paragraphs):
    import docx
    d = docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_csv_extracts_cells():
    att = A.validate_file("t.csv", b"a,b\n1,2\n")
    assert att.kind == "csv"
    assert "a" in att.extracted_text and "2" in att.extracted_text


def test_tsv_extracts_cells():
    att = A.validate_file("t.tsv", b"a\tb\n1\t2\n")
    assert att.kind == "tsv"
    assert "1" in att.extracted_text


def test_txt_decodes():
    att = A.validate_file("n.txt", "hello world".encode("utf-8"))
    assert att.extracted_text.strip() == "hello world"


def test_xlsx_extracts_cells():
    att = A.validate_file("s.xlsx", _xlsx_bytes([["h1", "h2"], [10, 20]]))
    assert att.kind == "xlsx"
    assert "h1" in att.extracted_text and "20" in att.extracted_text


def test_docx_extracts_paragraphs():
    att = A.validate_file("d.docx", _docx_bytes(["first para", "second para"]))
    assert "first para" in att.extracted_text and "second para" in att.extracted_text


def test_unknown_type_rejected():
    with pytest.raises(A.AttachmentValidationError):
        A.validate_file("x.exe", b"MZ\x90\x00")


def test_oversize_rejected():
    with pytest.raises(A.AttachmentValidationError):
        A.validate_file("t.txt", b"x" * (A.MAX_FILE_BYTES + 1))


def test_empty_extraction_rejected():
    # a .txt that decodes to only whitespace has no usable content
    with pytest.raises(A.EmptyExtractionError):
        A.validate_file("blank.txt", b"   \n  ")


def test_budget_truncates_combined_text():
    big = ("row,val\n" + "x,1\n" * 20000).encode("utf-8")  # well over 15000 chars
    atts = A.validate_files([("big.csv", big)])
    total = sum(len(a.extracted_text) for a in atts)
    assert total <= A.MAX_EXTRACTED_CHARS + 60  # + room for the marker
    assert "truncated" in atts[-1].extracted_text


def test_text_block_format():
    atts = A.validate_files([("t.csv", b"a,b\n1,2\n")])
    block = A.attachments_to_text_block(atts)
    assert block.startswith("\n\n[Attachment: t.csv]\n")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest utils/test_attachments.py -q`
Expected: FAIL (`ModuleNotFoundError` / `AttributeError: module 'utils.attachments'`).

- [ ] **Step 3: Implement `utils/attachments.py`**

```python
"""Validation + text extraction for student-uploaded non-image files.

Pure functions over ``(filename, bytes)`` — no Flask, no DB. Sibling to
``utils.uploads`` (images). Every supported type is extracted to plain text so
the tutor consumes it uniformly across providers and the per-message character
budget can be enforced (the real cost control — see the design spec).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import Path

# ext -> kind. TSV shares the CSV reader with a tab delimiter.
ALLOWED_FILE_EXTS: dict[str, str] = {
    ".csv": "csv",
    ".tsv": "tsv",
    ".xlsx": "xlsx",
    ".pdf": "pdf",
    ".docx": "docx",
    ".txt": "txt",
}

MAX_FILE_BYTES = 5 * 1024 * 1024      # 5 MB coarse gate (real cost control is the char budget)
MAX_EXTRACTED_CHARS = 15000           # ~4k tokens across all files in one message


class AttachmentValidationError(ValueError):
    """Bad type or oversize file."""


class AttachmentExtractionError(ValueError):
    """File matched a known type but could not be parsed (corrupt / missing parser)."""


class EmptyExtractionError(ValueError):
    """File parsed but yielded no usable text (e.g. scanned image-only PDF)."""


@dataclass(frozen=True)
class ValidatedAttachment:
    """An accepted upload: original filename, kind, extracted text, raw bytes."""

    filename: str
    kind: str
    extracted_text: str
    data: bytes

    @property
    def size_bytes(self) -> int:
        return len(self.data)


def _kind_for(filename: str) -> str | None:
    return ALLOWED_FILE_EXTS.get(Path(filename or "").suffix.lower())


def _extract_delimited(data: bytes, delimiter: str) -> str:
    text = data.decode("utf-8", errors="replace")
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return "\n".join(", ".join(cell for cell in row) for row in reader)


def _extract_txt(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def _extract_xlsx(data: bytes) -> str:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover
        raise AttachmentExtractionError("openpyxl is required to read .xlsx files.") from exc
    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise AttachmentExtractionError(f"Could not read spreadsheet: {exc}") from exc
    lines: list[str] = []
    for ws in wb.worksheets:
        for row in ws.iter_rows(values_only=True):
            cells = [("" if c is None else str(c)) for c in row]
            if any(cells):
                lines.append(", ".join(cells))
    return "\n".join(lines)


def _extract_docx(data: bytes) -> str:
    try:
        import docx
    except ImportError as exc:  # pragma: no cover
        raise AttachmentExtractionError("python-docx is required to read .docx files.") from exc
    try:
        doc = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise AttachmentExtractionError(f"Could not read document: {exc}") from exc
    return "\n".join(p.text for p in doc.paragraphs)


def _extract_pdf(data: bytes) -> str:
    try:
        import pypdf
    except ImportError as exc:  # pragma: no cover
        raise AttachmentExtractionError("pypdf is required to read .pdf files.") from exc
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:
        raise AttachmentExtractionError(f"Could not read PDF: {exc}") from exc


_EXTRACTORS = {
    "csv": lambda d: _extract_delimited(d, ","),
    "tsv": lambda d: _extract_delimited(d, "\t"),
    "txt": _extract_txt,
    "xlsx": _extract_xlsx,
    "docx": _extract_docx,
    "pdf": _extract_pdf,
}


def validate_file(filename: str, data: bytes) -> ValidatedAttachment:
    """Validate + extract one upload. Raises on bad type, oversize, or empty text."""
    if not data:
        raise AttachmentValidationError(f"'{filename}' is empty.")
    if len(data) > MAX_FILE_BYTES:
        raise AttachmentValidationError(
            f"'{filename}' is {len(data)} bytes; max is {MAX_FILE_BYTES} bytes."
        )
    kind = _kind_for(filename)
    if kind is None:
        raise AttachmentValidationError(
            f"'{filename}' is not a supported file type "
            f"({', '.join(sorted(ALLOWED_FILE_EXTS))})."
        )
    text = _EXTRACTORS[kind](data).strip()
    if not text:
        raise EmptyExtractionError(
            f"'{filename}' contained no readable text (a scanned/image-only file "
            "can't be read — attach the text or a screenshot instead)."
        )
    return ValidatedAttachment(filename=filename, kind=kind, extracted_text=text, data=data)


def validate_files(items: list[tuple[str, bytes]]) -> list[ValidatedAttachment]:
    """Validate each file, then truncate combined text to MAX_EXTRACTED_CHARS."""
    atts = [validate_file(name, data) for (name, data) in items]
    budget = MAX_EXTRACTED_CHARS
    out: list[ValidatedAttachment] = []
    for att in atts:
        if budget <= 0:
            text = f"[…truncated {len(att.extracted_text)} chars for length…]"
        elif len(att.extracted_text) > budget:
            dropped = len(att.extracted_text) - budget
            text = att.extracted_text[:budget] + f"\n[…truncated {dropped} chars for length…]"
            budget = 0
        else:
            text = att.extracted_text
            budget -= len(att.extracted_text)
        out.append(
            ValidatedAttachment(att.filename, att.kind, text, att.data)
            if text != att.extracted_text
            else att
        )
    return out


def attachments_to_text_block(atts: list["ValidatedAttachment"]) -> str:
    """Render attachments as labeled text blocks appended to a student message."""
    if not atts:
        return ""
    return "".join(f"\n\n[Attachment: {a.filename}]\n{a.extracted_text}" for a in atts)
```

- [ ] **Step 4: Add dependencies**

Append to `requirements.txt`:

```
openpyxl
python-docx
```

Then: `pip install openpyxl python-docx`

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest utils/test_attachments.py -q`
Expected: PASS (10 passed).

- [ ] **Step 6: Commit**

```bash
git add utils/attachments.py utils/test_attachments.py requirements.txt
git commit -m "feat(attachments): text extraction + validation for non-image uploads"
```

---

### Task 2: Combined attachment cap in `utils/uploads.py`

**Files:**
- Modify: `utils/uploads.py`
- Test: `utils/test_uploads_cap.py`

**Interfaces:**
- Consumes: `ValidatedImage` (existing), `ValidatedAttachment` from Task 1.
- Produces:
  - `MAX_ATTACHMENTS_PER_MESSAGE = 3`
  - `enforce_combined_cap(n_images: int, n_files: int) -> None` — raises `UploadValidationError` if `n_images + n_files > 3`.

- [ ] **Step 1: Write failing test**

```python
# utils/test_uploads_cap.py
import pytest
from utils.uploads import enforce_combined_cap, UploadValidationError, MAX_ATTACHMENTS_PER_MESSAGE


def test_cap_value():
    assert MAX_ATTACHMENTS_PER_MESSAGE == 3


def test_within_cap_ok():
    enforce_combined_cap(2, 1)  # 3 total — fine


def test_over_cap_raises():
    with pytest.raises(UploadValidationError):
        enforce_combined_cap(2, 2)  # 4 total
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest utils/test_uploads_cap.py -q`
Expected: FAIL (`ImportError: cannot import name 'enforce_combined_cap'`).

- [ ] **Step 3: Implement** — append to `utils/uploads.py`:

```python
MAX_ATTACHMENTS_PER_MESSAGE = 3  # images + files combined, per message


def enforce_combined_cap(n_images: int, n_files: int) -> None:
    """Reject a turn whose image + file count exceeds the per-message cap."""
    total = n_images + n_files
    if total > MAX_ATTACHMENTS_PER_MESSAGE:
        raise UploadValidationError(
            f"Too many attachments: {total} (max {MAX_ATTACHMENTS_PER_MESSAGE} per message)."
        )
```

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest utils/test_uploads_cap.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add utils/uploads.py utils/test_uploads_cap.py
git commit -m "feat(uploads): combined image+file per-message attachment cap"
```

---

### Task 3: `UploadedFile` model (shared mixin + per-app tables + relationship)

**Files:**
- Modify: `ui_core/db/models_common.py` (add `UploadedFileMixin`; add `uploaded_files` relationship to `MessageMixin`)
- Modify: `sandbox_ui/db/models.py` (add `UploadedFile`)
- Modify: `main_ui/db/models.py` (add `UploadedFile`)
- Test: `ui_core/test_uploaded_file_model.py`

**Interfaces:**
- Produces: `UploadedFileMixin` with `__tablename__ = "uploaded_files"` and columns `id`, `message_id` (FK messages.id ON DELETE CASCADE), `filename` (Text), `kind` (Text), `extracted_text` (Text), `size_bytes` (int), `data` (LargeBinary), `created_at`. Per-app `UploadedFile(UploadedFileMixin, Base)`. `Message.uploaded_files` relationship.

- [ ] **Step 1: Write failing test**

```python
# ui_core/test_uploaded_file_model.py
from sandbox_ui.db.models import UploadedFile


def test_columns_present():
    cols = {c.name for c in UploadedFile.__table__.columns}
    assert {"id", "message_id", "filename", "kind", "extracted_text",
            "size_bytes", "data", "created_at"} <= cols
    assert UploadedFile.__tablename__ == "uploaded_files"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest ui_core/test_uploaded_file_model.py -q`
Expected: FAIL (`ImportError: cannot import name 'UploadedFile'`).

- [ ] **Step 3: Add `UploadedFileMixin` to `ui_core/db/models_common.py`** (place directly after `UploadedImageMixin`, reusing the same imports `_BigIntPk`, `Text`, `LargeBinary`, `DateTime`, `_utcnow`, `ForeignKey`, `Mapped`, `mapped_column`, `relationship`, `declared_attr`, `datetime`):

```python
class UploadedFileMixin:
    """Columns + relationship for the ``uploaded_files`` table (non-image attachments)."""

    __tablename__ = "uploaded_files"

    id: Mapped[int] = mapped_column(_BigIntPk, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        _BigIntPk,
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # Plain text extracted at upload time — this is what reaches the tutor and is
    # re-injected into history every turn (persist-across-turns).
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(nullable=False)
    # Raw file bytes, stored in-DB like uploaded_images (Railway FS is ephemeral).
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    @declared_attr
    def message(cls) -> Mapped["Message"]:  # noqa: F821 - resolved per app
        """Relationship to the owning ``Message`` (back-populates ``uploaded_files``)."""
        return relationship(back_populates="uploaded_files")
```

- [ ] **Step 4: Add the `uploaded_files` relationship on `MessageMixin`**

Find the existing `uploaded_images` relationship in `MessageMixin` (same file) and add a sibling immediately after it:

```python
    @declared_attr
    def uploaded_files(cls) -> Mapped[list["UploadedFile"]]:  # noqa: F821
        """Non-image attachments on this message (back-populates ``message``)."""
        return relationship(back_populates="message", cascade="all, delete-orphan")
```

- [ ] **Step 5: Declare the per-app tables**

In `sandbox_ui/db/models.py`, next to `class UploadedImage(UploadedImageMixin, Base): pass`, add (and add `UploadedFileMixin` to the existing `from ui_core.db.models_common import ...` line):

```python
class UploadedFile(UploadedFileMixin, Base):
    pass
```

Do the identical addition in `main_ui/db/models.py`.

- [ ] **Step 6: Run to verify it passes**

Run: `python -m pytest ui_core/test_uploaded_file_model.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ui_core/db/models_common.py sandbox_ui/db/models.py main_ui/db/models.py ui_core/test_uploaded_file_model.py
git commit -m "feat(db): UploadedFile model mirroring UploadedImage"
```

---

### Task 4: `files` persistence service + reset helper + Alembic migration

**Files:**
- Create: `ui_core/services/files.py`
- Create: `sandbox_ui/services/files.py`
- Create: `main_ui/services/files.py`
- Create: `sandbox_ui/db/reset_uploaded_files.py`
- Create: `main_ui/db/migrations/versions/<autogen>_add_uploaded_files.py`
- Test: `ui_core/test_files_service.py`

**Interfaces:**
- Consumes: `ValidatedAttachment` (Task 1), `UploadedFile` (Task 3).
- Produces:
  - `ui_core.services.files.read_and_validate(files: list[FileStorage]) -> list[ValidatedAttachment]`
  - `ui_core.services.files.persist_files(db, *, message, files, uploaded_file_cls) -> list`
  - `ui_core.services.files.files_to_text(files: list[ValidatedAttachment]) -> str` (delegates to `attachments_to_text_block`)
  - Per-app `services/files.py` binding `UploadedFile` (mirrors `services/images.py`).

- [ ] **Step 1: Write failing test**

```python
# ui_core/test_files_service.py
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest ui_core/test_files_service.py -q`
Expected: FAIL (`ModuleNotFoundError: ui_core.services.files`).

- [ ] **Step 3: Implement `ui_core/services/files.py`**

```python
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
```

- [ ] **Step 4: Implement per-app wrappers**

`sandbox_ui/services/files.py`:

```python
"""sandbox_ui binding of the shared file-upload service."""

from __future__ import annotations

from sqlalchemy.orm import Session

from sandbox_ui.db.models import UploadedFile
from ui_core.services import files as _shared
from utils.attachments import ValidatedAttachment

read_and_validate = _shared.read_and_validate
files_to_text = _shared.files_to_text


def persist_files(db: Session, *, message, files: list[ValidatedAttachment]):
    """Insert one UploadedFile row per attachment, linked to *message*."""
    return _shared.persist_files(db, message=message, files=files, uploaded_file_cls=UploadedFile)
```

Create `main_ui/services/files.py` identically but importing `from main_ui.db.models import UploadedFile`.

- [ ] **Step 5: Reset helper for sandbox_ui** — `sandbox_ui/db/reset_uploaded_files.py`:

```python
"""One-off: create/rebuild the `uploaded_files` table for an existing Sandbox DB.

Sandbox builds its schema with ``create_all`` (creates missing tables, never
ALTERs). A DB created before ``UploadedFile`` existed has no ``uploaded_files``
table, so file inserts crash. This creates it (or rebuilds it) against the same
DB the app uses.

    python -m sandbox_ui.db.reset_uploaded_files
"""

from __future__ import annotations

from sandbox_ui.db.models import UploadedFile
from sandbox_ui.db.session import engine


def main() -> None:
    print(f"Target DB: {engine.url}")
    UploadedFile.__table__.drop(engine, checkfirst=True)
    UploadedFile.__table__.create(engine)
    print("Rebuilt 'uploaded_files' with the current schema.")
    print("Restart the Sandbox: python -m sandbox_ui")


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Alembic migration for main_ui**

Autogenerate against the model (run from repo root with main_ui's DB env configured):

Run: `python -m alembic -c main_ui/db/migrations/alembic.ini revision --autogenerate -m "add uploaded_files"`

Verify the generated file's `upgrade()` calls `op.create_table('uploaded_files', ...)` with columns matching Task 3. If autogenerate is unavailable in the environment, hand-write the migration mirroring `b7c4e1a9d2f0`'s structure with `op.create_table('uploaded_files', sa.Column('id', sa.BigInteger, primary_key=True), sa.Column('message_id', sa.BigInteger, sa.ForeignKey('messages.id', ondelete='CASCADE'), nullable=False), sa.Column('filename', sa.Text, nullable=False), sa.Column('kind', sa.Text, nullable=False), sa.Column('extracted_text', sa.Text, nullable=False), sa.Column('size_bytes', sa.Integer, nullable=False), sa.Column('data', sa.LargeBinary, nullable=False), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))` and a `drop_table` in `downgrade()`. Set `down_revision` to the current head (`b7c4e1a9d2f0`).

- [ ] **Step 7: Run service tests + sandbox reset**

Run: `python -m pytest ui_core/test_files_service.py -q`
Expected: PASS.
Run: `python -m sandbox_ui.db.reset_uploaded_files`
Expected: prints "Rebuilt 'uploaded_files'".

- [ ] **Step 8: Commit**

```bash
git add ui_core/services/files.py sandbox_ui/services/files.py main_ui/services/files.py \
        sandbox_ui/db/reset_uploaded_files.py main_ui/db/migrations/versions/ ui_core/test_files_service.py
git commit -m "feat(files): persistence service, reset helper, and migration for UploadedFile"
```

---

### Task 5: Persist-across-turns — inject extracted text into history

**Files:**
- Modify: `ui_core/services/conversation.py` (`get_history_for_tutor`, and `Models`)
- Test: `ui_core/test_history_injection.py`

**Interfaces:**
- Consumes: `UploadedFile` rows (Task 3).
- Produces: `get_history_for_tutor` appends each student message's `uploaded_files` extracted text to that message's model-facing `content` as `\n\n[Attachment: <name>]\n<text>`. `Models` gains an optional `UploadedFile: type | None = None` field.

- [ ] **Step 1: Write failing test**

```python
# ui_core/test_history_injection.py
from ui_core.services.conversation import _content_with_attachments


def test_appends_attachment_text():
    class Att:
        filename = "budget.csv"
        extracted_text = "a, b\n1, 2"
    out = _content_with_attachments("What does this show?", [Att()])
    assert out.startswith("What does this show?")
    assert "[Attachment: budget.csv]" in out
    assert "1, 2" in out


def test_no_attachments_returns_content_unchanged():
    assert _content_with_attachments("hi", []) == "hi"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest ui_core/test_history_injection.py -q`
Expected: FAIL (`ImportError: cannot import name '_content_with_attachments'`).

- [ ] **Step 3: Implement in `ui_core/services/conversation.py`**

Add the helper near `get_history_for_tutor`:

```python
def _content_with_attachments(content: str, attachments) -> str:
    """Append each attachment's extracted text to a message's model-facing content."""
    if not attachments:
        return content
    blocks = "".join(
        f"\n\n[Attachment: {a.filename}]\n{a.extracted_text}" for a in attachments
    )
    return f"{content}{blocks}"
```

Update `get_history_for_tutor` to eager-load and inject attachments for student turns:

```python
def get_history_for_tutor(db: Session, conversation: Any, *, models: Models) -> list[dict]:
    """Return prior messages as [{role, content}, ...], with student attachments
    re-injected into content so files persist across turns."""
    stmt = (
        select(models.Message)
        .where(models.Message.conversation_id == conversation.id)
        .order_by(models.Message.turn, models.Message.id)
    )
    msgs = db.execute(stmt).scalars().all()
    out: list[dict] = []
    for m in msgs:
        content = m.content
        if m.role == "student" and getattr(models, "UploadedFile", None) is not None:
            atts = list(getattr(m, "uploaded_files", []) or [])
            content = _content_with_attachments(content, atts)
        out.append({"role": m.role, "content": content})
    return out
```

Add `UploadedFile: type | None = None` to the `Models` dataclass (same file), so apps can bind it.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest ui_core/test_history_injection.py -q`
Expected: PASS.

- [ ] **Step 5: Bind `UploadedFile` in each app's `Models`**

In `sandbox_ui/services/conversation.py`, update `_MODELS = Models(Conversation=Conversation, Message=Message, UploadedImage=UploadedImage)` to also pass `UploadedFile=UploadedFile` (import it). Do the same in `main_ui/services/conversation.py`.

- [ ] **Step 6: Commit**

```bash
git add ui_core/services/conversation.py ui_core/test_history_injection.py \
        sandbox_ui/services/conversation.py main_ui/services/conversation.py
git commit -m "feat(history): re-inject file attachments into tutor history each turn"
```

---

### Task 6: Wire the chat route (both apps)

**Files:**
- Modify: `sandbox_ui/routes/chat.py`
- Modify: `main_ui/routes/chat.py`
- Test: `sandbox_ui/routes/test_chat_files.py`

**Interfaces:**
- Consumes: `services.files.read_and_validate` / `persist_files` / `files_to_text`, `enforce_combined_cap`, and (for the current turn) the injected student text.
- Produces: on a multipart request, `request.files.getlist("files")` are validated, capped with images, persisted, and their text appended to the current-turn `new_student_message` sent to the tutor.

- [ ] **Step 1: Write failing route test** (sandbox_ui; use the app's existing test client fixture pattern — model the file after any existing `sandbox_ui/routes/test_*` that posts to `/api/chat`):

```python
# sandbox_ui/routes/test_chat_files.py
import io
from utils.attachments import MAX_ATTACHMENTS_PER_MESSAGE


def test_too_many_attachments_rejected(client):
    data = {"text": "hi", "course": "supply_chain_design", "exercise": "1"}
    data["files"] = [(io.BytesIO(b"a,b\n1,2\n"), f"f{i}.csv") for i in range(4)]
    resp = client.post("/api/chat", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert resp.get_json()["error"] in ("too_many_attachments", "bad_file")


def test_bad_file_type_rejected(client):
    data = {"text": "hi", "course": "supply_chain_design", "exercise": "1",
            "files": [(io.BytesIO(b"MZ\x00"), "x.exe")]}
    resp = client.post("/api/chat", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "bad_file"
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest sandbox_ui/routes/test_chat_files.py -q`
Expected: FAIL (route ignores `files`; no 400).

- [ ] **Step 3: Modify `sandbox_ui/routes/chat.py`**

Near the existing image read (`upload_files = request.files.getlist("images")`), add:

```python
        upload_docs = request.files.getlist("files")
    else:
        src = request.get_json(silent=True) or {}
        upload_files = []
        upload_docs = []
```

Import at top: `from sandbox_ui.services import files as files_service` and `from utils.uploads import enforce_combined_cap`.

After the image validation block, validate files, enforce the combined cap, and fold text into the student turn:

```python
    try:
        attachments = files_service.read_and_validate(upload_docs)
    except AttachmentValidationError as exc:
        return _bad_request(str(exc), "bad_file")
    except EmptyExtractionError as exc:
        return _bad_request(str(exc), "empty_extraction")
    except AttachmentExtractionError as exc:
        return _bad_request(str(exc), "extraction_failed")

    try:
        enforce_combined_cap(len(images), len(attachments))
    except UploadValidationError as exc:
        return _bad_request(str(exc), "too_many_attachments")

    if not text and not images and not attachments:
        return _bad_request("text or an attachment is required", "missing_text")
    student_text = text or ("(File attached.)" if attachments else "(Image attached.)")
```

Import the attachment errors: `from utils.attachments import AttachmentValidationError, AttachmentExtractionError, EmptyExtractionError`.

Persist files alongside images (right after `images_service.persist_images(...)`):

```python
    if attachments:
        try:
            files_service.persist_files(db, message=student_msg, files=attachments)
        except Exception as exc:
            return _abort_with((jsonify({"error": "file_persist_failed",
                "reason": f"{type(exc).__name__}: {exc}"}), 500))
```

Fold attachment text into the message the tutor sees this turn. Where `new_student_message=student_text` is set in `stream_kwargs`, change to:

```python
        new_student_message=student_text + files_service.files_to_text(attachments),
```

- [ ] **Step 4: Apply the identical wiring to `main_ui/routes/chat.py`** (same structure — read `files`, validate, cap, persist, fold text). If main_ui's chat route diverges, preserve its existing control flow and only add the file branch mirroring the image branch.

- [ ] **Step 5: Run to verify it passes**

Run: `python -m pytest sandbox_ui/routes/test_chat_files.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add sandbox_ui/routes/chat.py main_ui/routes/chat.py sandbox_ui/routes/test_chat_files.py
git commit -m "feat(chat): accept, validate, persist, and inject non-image file attachments"
```

---

### Task 7: Frontend composers — accept files, render chips, enforce cap

**Files:**
- Modify: `sandbox_ui/static/js/chat.js`
- Modify: `main_ui/static/js/chat.js`
- Modify: the message-list API in `sandbox_ui/routes/history.py` and `main_ui/routes/history.py` (return attachment metadata)

**Interfaces:**
- Consumes: the `/api/chat` `files` field (Task 6); message-list JSON.
- Produces: composer appends selected files to the `FormData` under `files`; renders a `📎 <name>` chip per file; blocks selection beyond 3 combined attachments; past messages render chips from returned metadata.

- [ ] **Step 1: Locate the image-upload code in `sandbox_ui/static/js/chat.js`**

Search for where images are appended to `FormData` (`formData.append("images", ...)`) and where the file `<input>`/accept is defined. This is the pattern to mirror.

- [ ] **Step 2: Add a file input + accept list**

Add (or extend) a file input with:

```html
accept=".csv,.tsv,.xlsx,.pdf,.docx,.txt,image/png,image/jpeg"
```

- [ ] **Step 3: Append files to the request**

Where images are appended, add the selected non-image files:

```js
for (const f of selectedFiles) {
  formData.append("files", f, f.name);
}
```

- [ ] **Step 4: Render a chip per file and enforce the cap client-side**

```js
function renderFileChip(name) {
  const chip = document.createElement("span");
  chip.className = "attachment-chip";
  chip.textContent = "📎 " + name;
  return chip;
}
// before adding a new attachment:
if (selectedImages.length + selectedFiles.length >= 3) {
  showComposerError("Up to 3 attachments per message.");
  return;
}
```

- [ ] **Step 5: Return attachment metadata from the message-list API**

In `sandbox_ui/routes/history.py`, where each message is serialized (it already includes image metadata), add a sibling `attachments` array from `m.uploaded_files` with `{id, filename, kind}` (never bytes / extracted_text). Render those as chips on past messages using `renderFileChip`.

- [ ] **Step 6: Apply the identical changes to `main_ui/static/js/chat.js` and `main_ui/routes/history.py`.**

- [ ] **Step 7: Manual smoke test** (use the `run` skill or start the app)

Run: `python -m sandbox_ui` then open the UI, attach a small CSV, send, and confirm the tutor references the data and a chip shows on the message.

- [ ] **Step 8: Commit**

```bash
git add sandbox_ui/static/js/chat.js main_ui/static/js/chat.js sandbox_ui/routes/history.py main_ui/routes/history.py
git commit -m "feat(ui): file attachment input, chips, and cap in both composers"
```

---

### Task 8: End-to-end persist-across-turns test

**Files:**
- Test: `sandbox_ui/routes/test_chat_files_e2e.py`

- [ ] **Step 1: Write the test** — attach a CSV on turn 1, send two more text-only turns, and assert the tutor history built for turn 3 still contains the attachment text. Use `sandbox_ui.services.conversation.get_history_for_tutor` directly against the test DB after posting turns (mirror the fixtures used by other route tests; stub the tutor stream so no live LLM call is made):

```python
def test_file_persists_into_history_on_later_turn(client, db_session):
    # turn 1: attach CSV (tutor stream stubbed by the fixture)
    import io
    client.post("/api/chat", data={
        "text": "here is my data", "course": "supply_chain_design", "exercise": "1",
        "files": [(io.BytesIO(b"region,cost\nA,10\n"), "d.csv")],
    }, content_type="multipart/form-data")
    # ... send two more text-only turns to the same conversation_id ...
    from sandbox_ui.services.conversation import get_history_for_tutor
    convo = _latest_conversation(db_session)
    hist = get_history_for_tutor(db_session, convo)
    student_turns = [h for h in hist if h["role"] == "student"]
    assert any("[Attachment: d.csv]" in h["content"] and "region" in h["content"]
               for h in student_turns)
```

- [ ] **Step 2: Run**

Run: `python -m pytest sandbox_ui/routes/test_chat_files_e2e.py -q`
Expected: PASS.

- [ ] **Step 3: Full suite + commit**

Run: `python -m pytest -q`
Expected: PASS (no regressions).

```bash
git add sandbox_ui/routes/test_chat_files_e2e.py
git commit -m "test(chat): file attachment persists across turns end-to-end"
```

---

## Self-Review

**Spec coverage:** file types (T1) ✓, both apps (T3–T7) ✓, extract-to-text (T1) ✓, ≤3 combined cap (T2, T6, T7) ✓, 15k-char budget (T1) ✓, 5 MB/10 MB byte caps (T1; images unchanged) ✓, persist-across-turns (T5) ✓, error codes bad_file/too_many_attachments/extraction_failed/empty_extraction (T6) ✓, chips + accept (T7) ✓, migration for both apps (T4) ✓, tests incl. history replay (T8) ✓.

**Placeholder scan:** Task 4 Step 6 (Alembic autogenerate) and Task 6 Step 4 / Task 7 (main_ui mirroring) intentionally defer to "mirror the sandbox structure" because main_ui's exact route/JS layout must be read at execution time — the sandbox code is shown in full as the template. Task 7 references existing image-composer code that must be located first (Step 1). These are read-then-mirror steps, not missing content.

**Type consistency:** `ValidatedAttachment(filename, kind, extracted_text, data)` used consistently in T1/T4/T6; `persist_files(..., files=, uploaded_file_cls=)` matches between shared and per-app; `enforce_combined_cap(n_images, n_files)` matches T2/T6; `_content_with_attachments(content, attachments)` matches T5; attachment text format `\n\n[Attachment: <name>]\n<text>` identical in `attachments_to_text_block`, `files_to_text`, and `_content_with_attachments`.
