# utils

Shared, dependency-free utilities used across the tutor, student, and judge
runners and the web apps (`main_ui`, `sandbox_ui`). Each module owns one
cross-cutting concern that would otherwise be duplicated across call sites.

Everything public is re-exported from the package, so callers import from the
top level:

```python
from utils import read_exercise, discover_figures, build_multimodal_content
```

Most modules are standard-library only (no third-party deps); the exception is
`attachments.py`, which pulls in `openpyxl` and `python-docx` (plus the
already-used `pypdf`) to extract text from spreadsheet/document uploads — its
public API is imported directly (`from utils.attachments import ...`) rather
than re-exported from the package top level. Path-based helpers accept an
optional `curriculum_root` override (defaulting to `<repo>/curriculum`) so
they can be pointed at fixtures in tests.

## Modules

| Module | Purpose |
| ------ | ------- |
| [`parsing.py`](parsing.py) | Extract a JSON object from free-text LLM output. |
| [`curriculum.py`](curriculum.py) | Canonical `curriculum/<course>/…` path resolution. |
| [`figures.py`](figures.py) | Discover exercise figures and build multimodal content. |
| [`lectures.py`](lectures.py) | Load a course's lecture transcripts. |
| [`uploads.py`](uploads.py) | Validate student-uploaded images. |
| [`attachments.py`](attachments.py) | Validate + extract text from student-uploaded non-image files. |
| [`pricing.py`](pricing.py) | Best-effort USD cost estimation from model token usage. |
| [`tokens.py`](tokens.py) | Pure per-message token estimate for the chat composer's size cap. |

### `parsing.py`

- `extract_json_object(text)` — return the first brace-balanced `{…}` substring,
  or `None`. Used to pull a JSON object out of a model response (e.g. judge
  grades).

### `curriculum.py`

Single source of truth for the curriculum layout
(`curriculum/<course>/exercises/exercise_<N>.txt`,
`.../practices/practice_<N>.txt`). Names use non-padded integers (`1`, `2`, …);
resolvers normalize any input to that form.

- Directory resolvers: `course_dir`, `exercises_dir`, `practices_dir`
- Exercises: `exercise_path`, `exercise_exists`, `read_exercise` (missing →
  `""`), `discover_exercises` (sorted `["1", "2", …]`)
- Practice problems (parallel set): `practice_path`, `practice_exists`,
  `read_practice`, `discover_practice`
- Case studies (third content kind): `cases_dir`, `case_path`, `case_exists`,
  `read_case`, `discover_cases`, plus `cases_solutions_dir`
- Sub-problem focus (a single part of a multi-part file): `list_subproblems`,
  `subproblem_label` (both take `kind="exercise"|"practice"|"case"`), matching
  the kind's header prefix (`Graded Assignment N:` / `Practice Problem N:` /
  `Case Question N:`)
- Solutions (tutor-only correct answers): `solution_path`, `read_solution` (both
  take `kind="exercise"|"practice"|"case"`, reading
  `exercises_solutions/exercise_solution_<N>.txt`,
  `practices_solutions/practice_solution_<N>.txt`, or
  `cases_solutions/case_solution_<N>.txt`),
  plus the `*_solutions_dir` helpers and the
  `SOLUTION_CONTEXT_LABEL` constant prefixed to the injected answer block
- `list_courses()` — sorted ACTIVE course folder names (excludes `_archive/` and
  its contents)
- `list_archived_courses()` — sorted course folder names under `_archive/`

### `figures.py`

Turns curriculum figures into the multimodal content blocks LangChain forwards
to OpenAI/Anthropic vision models. Naming convention:
`exercise_<NN>_<slug>.{png,jpg,jpeg}`; a figure serves exactly one exercise.

- `discover_figures(course, exercise_number)` — matching figure paths, sorted;
  `[]` when absent
- `image_to_data_url(source, *, mime_type=None)` — base64 `data:` URL from a
  path or raw bytes
- `build_multimodal_content(text, figures=None)` — plain `text` when no figures,
  else a `[{text}, {image_url}, …]` block list; figure items may be paths,
  `data:` URL strings, or `(bytes, mime)` tuples
- `figure_filenames(figures)` — paths → filenames (for transcript records)
- `resolve_figure_filenames(course, filenames)` — the reverse, used by the judge
  to re-attach recorded figures; silently skips missing files

### `lectures.py`

- `load_lecture_transcripts(course)` — concatenate every `*.txt` under
  `curriculum/<course>/lectures/` (sorted, each labeled `[stem]`), joined by
  blank lines. `""` when the folder is missing or empty. Folded into the tutor's
  context so guidance is grounded in what was taught.

### `uploads.py`

Shared image-upload rules for the web apps' chat composers, so the two apps
can't drift. Pure functions over `(filename, mime, bytes)` — no Flask, no DB.

- Constants: `ALLOWED_IMAGE_MIMES` (PNG/JPEG only), `MAX_IMAGE_BYTES` (10 MB),
  `MAX_IMAGES_PER_MESSAGE` (3)
- `UploadValidationError` — raised on bad type / too big / too many
- `ValidatedImage` — frozen dataclass (`filename`, `mime_type`, `data`,
  `size_bytes`)
- `validate_image(filename, declared_mime, data)` — validates one upload;
  **sniffs the MIME from magic bytes** rather than trusting the client
- `validate_images(items)` — enforces the count cap and validates each
- `images_to_tuples(images)` — `ValidatedImage` → `(bytes, mime)` tuples for
  `build_multimodal_content`
- `MAX_ATTACHMENTS_PER_MESSAGE` (3) — images + non-image files combined, per
  message
- `enforce_combined_cap(n_images, n_files)` — raises `UploadValidationError`
  when the combined count exceeds the cap

### `attachments.py`

Validation + text **extraction** for student-uploaded non-image files (CSV,
TSV, XLSX, PDF, DOCX, TXT). Sibling to `uploads.py`: pure functions over
`(filename, bytes)` — no Flask, no DB. Every supported type is extracted to
plain text so the tutor consumes it uniformly and a per-message character
budget can be enforced. Adds two third-party deps: `openpyxl` (xlsx) and
`python-docx` (docx); csv/tsv/txt use the standard library and pdf uses the
existing `pypdf` dependency.

- `ALLOWED_FILE_EXTS` — extension → kind (`csv`, `tsv`, `xlsx`, `pdf`, `docx`,
  `txt`); `MAX_FILE_BYTES` (5 MB, per file); `MAX_EXTRACTED_CHARS` (15000, per
  message across all attached files)
- `AttachmentValidationError` — bad type or oversize file
- `AttachmentExtractionError` — recognized type that failed to parse (corrupt
  file or missing optional parser dependency)
- `EmptyExtractionError` — parsed successfully but yielded no usable text
  (e.g. a scanned, image-only PDF)
- `ValidatedAttachment` — frozen dataclass (`filename`, `kind`,
  `extracted_text`, `data`)
- `validate_file(filename, data)` — validates and extracts one upload; raises
  on bad type, oversize, or empty extracted text
- `validate_files(items)` — validates each `(filename, data)` pair, then
  truncates the combined extracted text to `MAX_EXTRACTED_CHARS` (appending a
  `[…truncated N chars for length…]` marker)
- `attachments_to_text_block(atts)` — renders validated attachments as
  `\n\n[Attachment: <filename>]\n<text>` blocks appended to a student message

### `pricing.py`

Best-effort USD cost estimation for model calls. Token **counts** come from
LangChain `usage_metadata` (exact); only the dollar conversion uses a small rate
table (`$`/1M tokens, verified 2026-07). Rates cover `claude-sonnet-5`,
`claude-sonnet-4-6`, `gpt-5.4`, and `text-embedding-3-small`, are cache-aware (`cache_read` /
`cache_write`), and any rate can be overridden with a `PRICE_<MODEL>_<KEY>` env
var. Date-stamped model ids (e.g. `gpt-5.4-2026-03-05`) normalize to their base key.

- `estimate_cost_usd(model, *, input_tokens, output_tokens, cache_read, cache_write)`
  — USD cost of one call; treats `input_tokens` as the full prompt and bills the
  non-cached remainder at the input rate
- `usage_from_message(msg)` — normalized
  `{input_tokens, output_tokens, cache_read, cache_write}` from a message's
  `usage_metadata` (zeros when unreported)
- `model_from_message(msg, fallback)` — the actual model id from
  `response_metadata`, else `fallback`
- `priced(model, usage)` — bundle a usage dict with its model, rounded `usd`, and
  a `rate_is_placeholder` flag
- `rate(model, key)` — the `$`/1M rate for one model/key, honoring `PRICE_*`
  overrides

#### What one message costs

The default tutor is **`claude-sonnet-5`** ($3/1M input, $15/1M output, cache
read $0.30/1M, cache write $3.75/1M). Each turn is billed in three parts:

- **Cached prefix** (the system prompt: about + pinned + exercise + tutor-only
  solution, plus full lecture transcripts in `full_context` mode). Static across
  a conversation, so it is written to cache once (cache-write) and re-read every
  later turn at ~0.1× input (cache-read). Anthropic's ephemeral cache has a
  **5-minute TTL** — a pause longer than that expires it and the next turn pays
  cache-write again.
- **Per-turn dynamic** (billed at full input rate): the student message, the
  growing history tail, and — in `rag` mode — the retrieved chunks (`k=3`, capped
  at ~8000 chars ≈ 2000 tok).
- **Output** (~500 tok for a typical Socratic reply) at $15/1M — usually the
  single largest line item.

Worked example, `ai_edge` HW1 (cached prefix ≈ 13–17k tok; token counts via a
tiktoken proxy, so ±~15%):

| Mode | Steady-state turn (cache hit) | First turn / cache miss |
| ---- | ----------------------------- | ----------------------- |
| `rag` (default) | **~$0.017** | ~$0.064 |
| `full_context` | **~$0.015** | ~$0.072 |

So a typical mid-conversation message is **~1.5–2¢** (≈ $15–17 per 1000
messages); the first turn of a fresh conversation, or any turn after a >5-min
gap, costs ~$0.06–0.07 because it re-writes the prefix to cache. A larger
exercise/solution or lecture set inflates the prefix, but caching keeps its
marginal per-turn cost small (cache-read is 0.1× input). This matches the
~2¢/message figure quoted in the top-level README.

### `tokens.py`

A pure per-message **token estimate** for the chat composer's size cap. No
tokenizer is available in the repo, so it approximates ~4 chars/token for text
(typed text + extracted attachment text) plus a flat per-image cost. Used
server-side in the chat handler and **mirrored by the browser composer** — keep
the constants in sync with `chat.js`.

- `estimate_message_tokens(text, extracted_texts, n_images)` — estimated token
  cost of one student message (text + attachment text + images)
- Constants: `CHARS_PER_TOKEN` (4), `TOKENS_PER_IMAGE` (1600, ~Claude's
  per-image maximum)

## Tests

Each module has a standalone test file (`test_<module>.py`) with **no pytest
dependency** — a small `_check()` harness prints `PASS`/`FAIL`, and `main()`
exits non-zero if any assertion fails. Run one module's tests with:

```powershell
python -m utils.test_curriculum
python -m utils.test_cases          # cases resolvers
python -m utils.test_subproblems    # multi-part sub-problem parsing
python -m utils.test_figures
python -m utils.test_lectures
python -m utils.test_uploads
python -m utils.test_tokens         # per-message token estimate
```

Fixtures use `tempfile` directories via the `curriculum_root` override;
`test_figures.py` additionally exercises the real checked-in curriculum figures.

`test_attachments.py` (covers `attachments.py`) and `test_uploads_cap.py`
(covers the `enforce_combined_cap` addition to `uploads.py`) are written
against **pytest** instead of the no-pytest harness; run them with
`pytest utils/test_attachments.py utils/test_uploads_cap.py`.

> Note: `parsing.py` currently has no test file.
