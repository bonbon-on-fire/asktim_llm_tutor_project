# Non-image file attachments — design

**Date:** 2026-07-09
**Status:** Approved, ready for implementation
**Source:** CTL.SC2x staff-meeting item — "Support opening attached-file input as tables and other non-image file types (not just images)."

## Problem

Today the tutor accepts per-message uploads only as **PNG/JPEG images**. The validator in
[`utils/uploads.py`](../../../utils/uploads.py) hard-rejects everything else (magic-byte sniffed;
GIF/SVG/PDF explicitly excluded). Validated images flow to the vision model as `image_url` blocks
via [`build_multimodal_content`](../../../utils/figures.py). Students need to attach **tables and
other documents** (CSV/TSV, XLSX, PDF, DOCX, TXT) so the tutor can reason over them.

## Decisions (locked with the user)

| Question | Decision |
|---|---|
| File types | CSV, TSV, XLSX, PDF, DOCX, TXT |
| Apps | Both `sandbox_ui` and `main_ui` (shared code in `utils/` + `ui_core/`) |
| How the model consumes files | **Extract to text uniformly** (no native PDF blocks) |
| Attachments per message | **Up to 3 total**, any mix of images + files |
| Per-message extracted-text budget | **~15,000 chars (~4k tokens)** across all attachments; truncate beyond with a marker |
| Per-file byte cap | **10 MB images / 5 MB files** (coarse gate only) |
| Persistence | **Persist across turns** — re-inject stored extracted text each turn |

### Why extract-to-text, not native PDF

Native PDF document blocks are provider-specific (Claude vs GPT differ) and, critically, the
~15k-char cost budget can only be enforced on text we have extracted and measured. Native PDF cost
is opaque and unbounded. Extraction keeps cost predictable and behavior identical across the `gpt`
and `claude` tutors.

### Cost impact (measured baseline)

Current production cost is **~1.87¢/message** (tutor-only, Claude Sonnet 4.6, RAG `k=3`, caching;
measured across 120 transcripts). A max-budget file adds ~4k tokens ≈ **~1.2¢ once at full price**
on the turn it's attached (~+65% on that single message), then **~0.12¢/turn** while the prompt
cache is warm (0.1× cache-read). The 15k-char budget is the real cost control — without it a 2 MB
CSV would be ~500k tokens ≈ $1.50+/turn.

## Architecture

Mirror the existing image pipeline exactly, swapping the `image_url` block for an extracted-text
block. Key facts that shape this:

- **History is text-only.** [`get_history_for_tutor`](../../../ui_core/services/conversation.py)
  returns `[{role, content: str}]`; past-turn images are never replayed — they survive only as the
  `"(Image attached.)"` placeholder. So "persist across turns" is achieved by having the history
  builder append each past student turn's stored extracted text to that turn's model-facing content.
- **Attachments are stored separately from display text.** `UploadedImage` rows hold the bytes; the
  bubble shows a placeholder; the image block is injected at tutor-call time.

### Components

1. **`utils/attachments.py`** (new) — pure functions, no Flask/DB. Sibling to `utils/uploads.py`.
   - Detect kind by magic bytes + extension (never trust client MIME).
   - One extractor per kind: CSV/TSV → stdlib `csv`; TXT → decode; XLSX → `openpyxl`;
     DOCX → `python-docx`; PDF → `pypdf` (already a RAG dep).
   - Enforce 5 MB/file byte cap; reject unknown types.
   - Truncate combined extracted text to 15,000 chars, appending
     `\n[…truncated N chars for length…]`.
   - Returns `ValidatedAttachment(filename, kind, extracted_text, data)`.
   - New dependencies: `openpyxl`, `python-docx`.

2. **`utils/uploads.py`** (extend) — the "≤ 3 attachments total" cap spans images + files, so a small
   combined check runs in the route after both validators. Images keep the 10 MB cap; the existing
   5-image constant is superseded by the shared cap of 3.

3. **`UploadedFile` model + `ui_core/services/files.py`** (new) — mirror `UploadedImage` /
   [`ui_core/services/images.py`](../../../ui_core/services/images.py): a table
   (`filename`, `kind`, `extracted_text`, `data` bytes, FK to message) declared in each app's
   `db/models.py`, plus a shared persist/fetch service. Ship a `reset_uploaded_files.py` helper
   (mirroring the existing `reset_uploaded_images.py`) for existing dev DBs.

4. **`get_history_for_tutor`** (enhance, in `ui_core/services/conversation.py`) — for each past
   student message, append its attachments' `extracted_text` to that message's model-facing content
   as `\n\n[Attachment: <name>]\n<text>`. The current turn injects the same way. Display content
   (the chat bubble) stays clean — attachment text lives only in the model-facing history.

5. **`chat.py`** (both apps) — read a new `files` multipart field alongside `images`; validate both;
   enforce the combined cap; persist both linked to the student message. No change to the SSE
   streaming path.

6. **Frontend** (both composers) — `accept` the new extensions; render a **chip** (`📎 name`) per
   file instead of a thumbnail; enforce the 3-attachment cap client-side. The message-list API
   returns attachment metadata (filename/kind, not bytes) so past-message chips render on reload.

## Error handling

Clean 400s with codes: `bad_file` (unknown type / too big), `too_many_attachments`,
`extraction_failed` (corrupt file), `empty_extraction` (e.g. scanned image-only PDF — tell the
student to attach text or an image instead). Extraction failures never 500. Scanned/image-only PDFs
are not OCR'd (same limitation as the RAG PDF path) — they hit `empty_extraction`.

## Testing

- `utils/attachments.py`: unit tests per extractor (small CSV/TSV/XLSX/PDF/DOCX/TXT fixtures),
  byte-cap rejection, budget truncation, unknown-type rejection.
- Combined-cap test in the route (4 attachments → 400).
- History-replay test: attach a file on turn 1, assert its text is in the model history on turn 3.

## Migration

The new `UploadedFile` table must be created in both apps' databases (dev via the reset helper;
prod via the deploy path).

## Out of scope

- Native PDF/document blocks.
- OCR of scanned PDFs / images-as-tables.
- Server-side virus scanning (byte cap + type sniffing only).
