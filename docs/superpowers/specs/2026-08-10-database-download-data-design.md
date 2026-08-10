# database_ui "Download data" export â€” design

**Date:** 2026-08-10
**App:** `database_ui` (read-only review dashboard)

## Goal

Add a **Download data** button to the `database_ui` sidebar. It opens a modal â€”
mirroring the sandbox "Edit context" button/modal pattern â€” where a reviewer
multi-selects **courses** and **assignments** (exercise numbers), then downloads
a single **CSV** containing one row per message across every matching
conversation.

This app is **read-only by construction** (see `database_ui/README.md`): no
writes, no migrations, per-request session always rolls back. The export is pure
`SELECT` and preserves that guarantee.

## Decisions (locked)

- **Export grain:** one row per message (student + tutor turns).
- **Format:** CSV only. UTF-8 **with BOM** so Excel opens it cleanly. No new
  Python dependencies (stdlib `csv`).
- **Columns:** full fidelity â€” include `pedagogical_reasoning`,
  `retrieved_context` (raw JSON string), `usage_json` (raw JSON string), and an
  `image_count`.
- **Assignment picker:** scoped to the selected courses, grouped under each
  course heading, **all checked by default**. Unchecking narrows.

## Endpoints

Two new routes in `database_ui/routes/database.py`, behind the existing
before-request auth gate. Both read-only.

### `GET /api/export/filters`

Populates the modal. Returns distinct courses and, per course, its distinct
assignments:

```json
{
  "courses": [
    {
      "course": "supply_chain_design",
      "course_name": "MIT CTL.SC2x Supply Chain Design",
      "assignments": [
        {"exercise_number": "1.1", "exercise_kind": "exercise"},
        {"exercise_number": "2.3", "exercise_kind": "practice"}
      ]
    }
  ]
}
```

Backed by a single `SELECT DISTINCT course, exercise_number, exercise_kind FROM
conversations`, grouped in Python into the nested shape. Courses sorted by
display name; assignments sorted within each course (natural-ish: by
`exercise_number`).

### `GET /api/export.csv`

Streams the CSV. Selection passed as **repeated query params**:

- `course=<key>` â€” one per selected course (used to keep the picker honest; the
  authoritative filter is the assignment pairs below).
- `assignment=<course_key>::<exercise_number>` â€” one per selected
  (course, assignment) pair.

**Why the scoped `course::exercise_number` key:** the same `exercise_number`
string can appear under different courses, so the *pair* is the real identity.
The server re-derives the message set from these pairs â€” it never trusts a
client-supplied list of conversation/message ids.

Response headers:

- `Content-Type: text/csv; charset=utf-8`
- `Content-Disposition: attachment; filename="asktim-export-<n>-msgs.csv"`
  (`<n>` = row count when known; a static name is acceptable if streaming before
  the count is known â€” see Implementation notes)
- Body begins with a UTF-8 BOM (`ï»¿`).

## CSV schema

One row per message. Column order:

```
conversation_id, course, course_name, exercise_number, exercise_kind,
focus_problem, username, started_at, last_active_at,
turn, role, content, pedagogical_reasoning, rating,
model, cost_usd, usage_json, retrieved_context, image_count, created_at
```

- `course_name` resolved via `database_ui/courses.py::course_display_name`.
- `model` parsed from `usage_json` via `ui_core.usage.model_from_usage_json`
  (same as the transcript view); blank when absent.
- `usage_json` and `retrieved_context` written as their **raw stored JSON
  strings** (lossless). The stdlib `csv` writer quotes/escapes embedded
  newlines, commas, and quotes.
- `image_count` from a grouped count over `uploaded_images` (never bytes).
- `username` blank for anonymous rows.
- Row ordering: `conversation.last_active_at DESC`, then `turn`, then
  `message.id` â€” the same order the transcript view uses.

## Services layer

New functions in `database_ui/services/conversations.py` (all read-only):

- `list_export_filters(db) -> list[dict]` â€” the nested courseâ†’assignments shape
  for `/api/export/filters`.
- `iter_export_rows(db, pairs) -> Iterator[dict]` (or `list[dict]`) â€” given the
  set of `(course, exercise_number)` pairs, yield one dict per message with all
  export columns. Joins `conversations` â†’ `messages`, batches the
  `image_count` per message (grouped query, no N+1), and reuses
  `model_from_usage_json`.

The route turns those dicts into CSV rows with stdlib `csv.writer` /
`csv.DictWriter`.

## Frontend

Files: `database_ui/templates/index.html`, `database_ui/static/js/database.js`,
`database_ui/static/css/database.css`.

- **Button:** a **Download data** button in the sidebar header (download-arrow
  SVG), styled to match the existing sidebar controls.
- **Modal:** clicking fetches `/api/export/filters`, then opens a modal overlay
  using the app's existing modal/error styling conventions:
  - **Courses** section â€” checkbox list + a "Select all" toggle.
  - **Assignments** section â€” scoped to the checked courses, grouped under each
    course heading, **all checked by default**. Toggling a course adds/removes
    its assignment group live.
  - Footer: **Cancel** and **Download CSV** (disabled when the selection is
    empty).
- **Download:** **Download CSV** builds the query string from the checked pairs
  and navigates to `/api/export.csv?...` via `window.location` (plain browser
  download â€” no blob juggling). Modal closes.

## Error handling

- `/api/export/filters` reuses the existing `_is_schema_drift` check â†’ 503
  `{"error":"schema_outdated","message":"Redeploy askTIM-main to run
  migrations"}`, same as `/api/conversations`.
- `/api/export.csv` with no matching messages â†’ a valid CSV with just the header
  row (harmless empty file), **not** an error.
- Malformed / empty selection (no `assignment` params) â†’ 400.
- Query failure (non-drift) â†’ 500 `{"error":"query_failed"}` consistent with the
  existing endpoint.

## Implementation notes

- **Streaming vs. filename count:** if the response streams, the total row count
  isn't known when headers are written. Acceptable resolutions: (a) use a static
  `filename="asktim-export.csv"`, or (b) materialize rows to count first (fine
  for review-scale volumes). Prefer (a) + streaming to stay cheap on large
  exports. Decide during implementation; either satisfies the design.
- No changes to `db/models.py` are required â€” `focus_problem`, `rating`,
  `cost_usd`, `usage_json`, `retrieved_context` are already mapped.

## Testing

- **Service tests** (SQLite fixture DB):
  - `list_export_filters` returns distinct courses with correctly grouped,
    de-duplicated assignments.
  - `iter_export_rows` emits the right columns and ordering; `image_count`
    aggregates correctly; only selected `(course, assignment)` pairs are
    included; an empty pair set yields no rows.
- **Route test:**
  - `/api/export.csv` returns `text/csv`, the attachment `Content-Disposition`,
    and a leading BOM.
  - Selection filtering excludes rows from non-selected course/assignment pairs.
  - Empty selection â†’ 400; no-match selection â†’ header-only CSV.
