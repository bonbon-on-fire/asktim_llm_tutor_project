# Practice problems selectable by URL — design

**Date:** 2026-07-16
**Status:** Approved (design), pending implementation plan
**Scope:** `main_ui` and `sandbox_ui`

## Problem

Students can only reach graded **exercises** by URL
(`/embed?course=<c>&exercise=<n>`). The curriculum also ships a parallel
**practice-problem** track (`curriculum/<course>/practices/practice_<n>.txt`),
but there is no URL that opens a practice problem in the tutor. A URL such as
`/embed?course=supply_chain_design&practice=7` today silently ignores
`practice=7`, falls back to the default exercise, and loads the wrong problem
with no error.

Goal: make `practice=<n>` a first-class sibling of `exercise=<n>` in the URL, so
that a practice problem flows all the way into the tutor's context (not just the
page).

## Key finding: sandbox already has the backend

`sandbox_ui` already implements the practice concept end-to-end, driven by its
Create-context **wizard** (a POST field `exercise_kind`), NOT by a URL param:

- `sandbox_ui/routes/_validation.py` — `validate_practice`, `list_practice`,
  `validate_selection(course, number, kind)`.
- `sandbox_ui/routes/chat.py` — reads `exercise_kind` from the request, validates,
  persists it.
- `sandbox_ui/services/conversation.py` — stores `exercise_kind`.
- `sandbox_ui/services/tutor_bridge.py` — its own `build_assignment_text` branches
  on `exercise_kind` (loads `practice_path` + `read_solution(kind="practice")`).
- `sandbox_ui/db/models.py` — `Conversation.exercise_kind` column
  (`"exercise"` default), backfilled by `_reconcile_columns()` on boot.
- `sandbox_ui/static/js/chat.js` — threads `config.exerciseKind` into the POST and
  labels sidebar rows "Practice N" vs "Exercise N".

`main_ui` has **none** of this. `utils/curriculum.py` already provides the shared
helpers (`practice_path`, `practice_exists`, `discover_practice`,
`read_solution(kind="practice")`).

So the work per app differs:

| Layer | sandbox_ui | main_ui |
|---|---|---|
| `validate_practice` / selection | exists | add (mirror sandbox) |
| `/embed` reads `?practice=` | add | add |
| chat handler reads `exercise_kind` | exists | add |
| `exercise_kind` DB column | exists | add (Alembic migration) |
| practice-aware tutor bridge | its own override | add to shared `ui_core` bridge |
| frontend threads `exercise_kind` | exists | add |

## URL contract (both apps)

```
/embed?course=<c>&exercise=<n>            -> exercise_kind = "exercise"  (unchanged)
/embed?course=<c>&practice=<n>            -> exercise_kind = "practice"
/embed?course=<c>&exercise=<a>&practice=<b>  -> 404 "cannot specify both exercise and practice"
```

- Bare `/` is unchanged: default course, default exercise, `exercise_kind="exercise"`.
- An explicitly invalid `practice` number 404s, exactly like an invalid
  `exercise` today (via `validate_practice`).
- **Both params present is rejected with a 404** (user decision) — no silent
  wrong-problem, consistent with existing bad-param behavior.
- `tutor` remains locked to `DEFAULT_TUTOR` in production (unchanged).

## Data flow (mirrors the existing `exercise` path)

1. `/embed` resolves `(number, kind)` from query params, rejects both-present,
   validates the number against the on-disk curriculum, and puts `exercise_kind`
   into `tutor_config` passed to `embed.html`.
2. Frontend `chat.js` appends `exercise_kind` to the `/api/chat` request
   (sandbox already does this; main_ui adds one field).
3. `/api/chat` reads `exercise_kind`, validates the selection when **starting** a
   new conversation, and stores it on the `Conversation` row.
4. The tutor bridge loads `practice_<n>.txt` + its practice solution instead of
   `exercise_<n>.txt` when `exercise_kind == "practice"`.
5. Continuations replay the conversation's **stored** kind and are not
   re-validated — the same guard the code already applies to course/exercise.

## Tutor bridge (approach A — chosen)

Make the shared `ui_core.tutor_bridge.build_assignment_text` **kind-aware**:
read `exercise_kind` from `ctx` (default `"exercise"`), and when it is
`"practice"` resolve `practice_path(course, number)` and
`read_solution(course, number, kind="practice")`, labelling the block
"Practice problem:" instead of "Exercise:".

- `main_ui` uses the shared base method directly, so it gains practice support
  with no main_ui-specific bridge override.
- `sandbox_ui` overrides `build_assignment_text` already, so it is **untouched**
  — zero regression risk to the working sandbox, and no duplicated practice
  branch inside main_ui.

Rejected alternative (B): duplicate a practice-aware `build_assignment_text`
inside main_ui. More duplication, no benefit over A.

Note: the RAG week cap (`_week_for_exercise`) and figure discovery already key
off the numeric `exercise`/number and the shared week mapping, so practice
numbers reuse the same week logic (a practice and exercise of the same number
share a week). No change needed there.

## Database

Add to `main_ui`'s `Conversation` model:

```
exercise_kind: TEXT NOT NULL DEFAULT 'exercise'   # "exercise" | "practice"
```

- Delivered as a **new Alembic migration** under
  `main_ui/db/migrations/versions/`. It auto-applies on deploy because the
  entrypoint runs `alembic upgrade head` against each service's `DATABASE_URL`
  (so both `askTIM-main-beta` and `askTIM-main-beta-plus` get the column).
- Additive + server default `'exercise'` => existing rows are unaffected and read
  back as exercises. Backward compatible.
- `main_ui`'s `find_or_create_conversation` / conversation service gain an
  `exercise_kind` parameter (default `"exercise"`), mirroring
  `sandbox_ui/services/conversation.py`.
- `sandbox_ui` needs **no** migration: it already has the column via its
  `_reconcile_columns()` boot step.

`exercise_number` continues to hold the numeric value for both kinds (same
semantics sandbox already uses); `exercise_kind` disambiguates.

## Validation (main_ui, mirroring sandbox)

Add to `main_ui/routes/_validation.py`:

- `validate_practice(course, practice)` — missing / non-digit / no
  `practice_<n>.txt` => failure dict, identical shape to `validate_exercise`.
- A selection resolver used by `/embed` and `/api/chat` that, given the raw
  `exercise` and `practice` params:
  - both present => a distinct failure (mapped to 404 "cannot specify both"),
  - `practice` present => validate as practice, `kind="practice"`,
  - else => validate as exercise, `kind="exercise"` (existing behaviour).

## Frontend

- `main_ui/routes/embed.py` and `sandbox_ui/routes/embed.py`: read `practice`,
  apply the both-present rejection, set `exercise_kind` in `tutor_config`.
- `main_ui/static/js/chat.js`: append `exercise_kind` to the POST body (the
  `FormData` around lines 871-893 and the JSON payload path). Initialise it from
  the server-rendered `config`.
- `sandbox_ui`: its `chat.js` already sends `exercise_kind`; only its
  `embed.py` + embed template need to seed `config.exerciseKind` from the URL.
- Sidebar label: sandbox already shows "Practice N"; main_ui's `chat.js`
  sidebar (`Exercise ${n}`) should show "Practice N" when the row's
  `exercise_kind === "practice"` (small, matches sandbox).

## Testing

- `main_ui`: unit tests for `validate_practice` and the both-params rejection
  (mirror `sandbox_ui/routes/test_validation_practice.py`).
- Shared bridge: a test that `build_assignment_text(..., exercise_kind="practice")`
  resolves the practice file + practice solution (mirror
  `sandbox_ui/services/test_tutor_bridge_practice.py`).
- Route-level: `/embed?practice=<n>` renders; `?exercise=&practice=` 404s;
  invalid practice 404s.

## Out of scope (YAGNI)

- The `database_ui` (askTIM-database) conversation browser labels every row
  "Exercise N" and does not read `exercise_kind`; it also points at beta's DB,
  not beta-plus, so practice conversations will not appear there. A "Practice N"
  label there is a possible later follow-up.
- No new practice content is authored; only existing `practices/*.txt` are
  surfaced.
- The tutor prompt stays locked to `DEFAULT_TUTOR`; no per-kind prompt changes.
