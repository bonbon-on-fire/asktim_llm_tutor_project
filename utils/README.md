# utils

Shared, dependency-free utilities used across the tutor, student, and judge
runners and the web apps (`main_ui`, `sandbox_ui`). Each module owns one
cross-cutting concern that would otherwise be duplicated across call sites.

Everything public is re-exported from the package, so callers import from the
top level:

```python
from utils import read_exercise, discover_figures, build_multimodal_content
```

All modules are standard-library only (no third-party deps). Path-based helpers
accept an optional `curriculum_root` override (defaulting to `<repo>/curriculum`)
so they can be pointed at fixtures in tests.

## Modules

| Module | Purpose |
| ------ | ------- |
| [`parsing.py`](parsing.py) | Extract a JSON object from free-text LLM output. |
| [`curriculum.py`](curriculum.py) | Canonical `curriculum/<course>/…` path resolution. |
| [`figures.py`](figures.py) | Discover exercise figures and build multimodal content. |
| [`lectures.py`](lectures.py) | Load a course's lecture transcripts. |
| [`uploads.py`](uploads.py) | Validate student-uploaded images. |

### `parsing.py`

- `extract_json_object(text)` — return the first brace-balanced `{…}` substring,
  or `None`. Used to pull a JSON object out of a model response (e.g. judge
  grades).

### `curriculum.py`

Single source of truth for the curriculum layout
(`curriculum/<course>/exercises/exercise_<NN>.txt`,
`.../practices/practice_<NN>.txt`). Names are strict two-digit (`01`, `02`, …).

- Directory resolvers: `course_dir`, `exercises_dir`, `practices_dir`
- Exercises: `exercise_path`, `exercise_exists`, `read_exercise` (missing →
  `""`), `discover_exercises` (sorted `["01", "02", …]`)
- Practice problems (parallel set): `practice_path`, `practice_exists`,
  `read_practice`, `discover_practice`
- `list_courses()` — sorted course folder names

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
  `MAX_IMAGES_PER_MESSAGE` (5)
- `UploadValidationError` — raised on bad type / too big / too many
- `ValidatedImage` — frozen dataclass (`filename`, `mime_type`, `data`,
  `size_bytes`)
- `validate_image(filename, declared_mime, data)` — validates one upload;
  **sniffs the MIME from magic bytes** rather than trusting the client
- `validate_images(items)` — enforces the count cap and validates each
- `images_to_tuples(images)` — `ValidatedImage` → `(bytes, mime)` tuples for
  `build_multimodal_content`

## Tests

Each module has a standalone test file (`test_<module>.py`) with **no pytest
dependency** — a small `_check()` harness prints `PASS`/`FAIL`, and `main()`
exits non-zero if any assertion fails. Run one module's tests with:

```powershell
python -m utils.test_curriculum
python -m utils.test_figures
python -m utils.test_lectures
python -m utils.test_uploads
```

Fixtures use `tempfile` directories via the `curriculum_root` override;
`test_figures.py` additionally exercises the real checked-in curriculum figures.

> Note: `parsing.py` currently has no test file.
