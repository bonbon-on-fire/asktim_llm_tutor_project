# sandbox_ui — AskTIM Sandbox

**🔗 Live: <https://asktim-sandbox.up.railway.app/>**

Developer/TA **testing website** for the tutor. It mirrors the student-facing
[`main_ui/`](../main_ui/README.md) chat experience — token-streamed replies,
persistent cross-session history, username + password identity — but adds a
**Create context** wizard so a tester can switch course and exercise on the fly
(picking from built-in options, with a toggleable lectures step and a RAG mode
selector), and runs against its **own separate database** so test chats never touch
production data.

Branding is deliberately distinct from production: the accent is teal-blue
(`#126f9a`) instead of MIT crimson, and the header reads **AskTIM · Sandbox Beta+**.

## What it shares with main_ui

- iframe-style chat at `/embed?course=...&exercise=...&tutor=...` (and a bare `/` that uses defaults)
- Server-Sent Events streaming — tutor replies token-by-token, `pedagogical-reasoning` hidden server-side
- Sanitized-markdown rendering of tutor replies (tables/lists/bold) — `marked` → `DOMPurify`, same `setMessageContent()` path as `main_ui`
- Conversation / Message / Student tables; username + password identity (bcrypt), cross-browser history sidebar
- The same tutor pipeline via `tutor.run_tutor` (through `services/tutor_bridge.py`)
- **Paired solution as tutor-only reference** — when the current problem has a matching solution file, `build_assignment_text` injects it (via [`utils.curriculum.read_solution`](../utils/curriculum.py)) right after the exercise as a "correct answer & worked solution" block. It's deterministic (keyed by problem number), given to the tutor but **never** the student, and never retrieved via RAG. Skipped only for problems with no solution file yet
- **Curriculum figures** auto-attached to the tutor — figures matching the exercise (`curriculum/<course>/figures/exercise_<NN>_*`) are sent as multimodal input on every turn via [`utils.figures.discover_figures`](../utils/figures.py)
- **Per-course lecture transcripts** — a course's `lectures/*.txt` fold into the tutor context via [`utils.lectures.load_lecture_transcripts`](../utils/lectures.py). In the Sandbox this is a dedicated **Lectures** wizard step, toggleable per conversation (and skipped in RAG mode, where lecture material is retrieved instead)
- **Student image uploads** — PNG/JPEG attachments (paperclip, drag-and-drop, or clipboard paste, up to 5 × 10 MB) sent to the tutor as multimodal input, stored in `uploaded_images.data` (BYTEA) and re-served via `GET /api/image/<id>`. Same shared validation ([`utils/uploads.py`](../utils/uploads.py)) and frontend as `main_ui`, including the click-to-enlarge image lightbox (staged or sent; backdrop / × / Esc to close)
- **Student document uploads** — CSV, TSV, XLSX, PDF, DOCX, and TXT attachments (same paperclip/drag-and-drop composer, shown as a file-icon chip rather than a thumbnail) are validated and text-extracted server-side ([`utils/attachments.py`](../utils/attachments.py); per-file cap 5 MB, per-message extracted-text budget 15,000 chars) and stored in the `uploaded_files` table. Images and documents share one combined cap of 3 attachments per message. The extracted text is re-injected into the tutor's history on every later turn so attachments stay "readable" across the conversation, even though the student-facing bubble just shows the filename
- **Per-message feedback** — a thumbs up / thumbs down control renders below each tutor message (outside the bubble); clicking sets the message's rating to +1 or -1, and clicking the active thumb again clears it back to 0. Each thumb posts to `POST /api/message/<id>/rating` and the state is persisted on the `messages.rating` column so it replays with history. (This replaces the older non-blocking 1-5 star toast, which has been removed; the dormant `POST /api/feedback` route remains but is no longer used)

## Architecture: a thin shell over `ui_core`

Like `main_ui`, `sandbox_ui` is a thin app built on the shared `ui_core`
package, plus its own sandbox-specific additions on top:

- `run_app.py` builds the app via `ui_core.app_factory.create_app(...)`
  (Flask construction, template loader, session/db-session hooks, `/health`).
  Its `on_startup` runs `Base.metadata.create_all(engine)` then
  `_reconcile_columns()` — sandbox_ui has no Alembic, so `_reconcile_columns()`
  `ALTER TABLE ... ADD COLUMN`s any model column missing from an
  already-existing table on the long-lived Sandbox DB (see
  [Database](#database) below).
- `services/conversation.py`, `services/students.py`, `services/images.py`,
  `services/files.py`, and `services/feedback.py` are thin wrappers that bind
  sandbox_ui's own model classes to the shared, app-agnostic logic in
  `ui_core.services.*`. `services/tutor_bridge.py` defines `SandboxTutorBridge`,
  a subclass of `ui_core.tutor_bridge.TutorBridge` that overrides its hooks
  (`cache_key`, `build_assignment_text`) to inject sandbox_ui's lectures-toggle
  and RAG-mode behavior; the other hooks (`prepare_ctx`, `build_system_prompt`,
  `turn_attachments`) are inherited from the base. **Per-turn RAG is the default context mode** when selected via the wizard; when RAG retrieval yields no results (including a missing index), both apps fail closed with an error banner and `TUTOR_CONTEXT_MODE=full_context` is the escape hatch — see [`rag/README.md`](../rag/README.md#mandatory-rag-fail-closed).
- `db/models.py` defines sandbox_ui's own `Conversation` (carrying its
  sandbox-only columns — `exercise_kind`, `lectures_enabled`, `context_mode`, and
  `provider`) but pulls `Message`, `Student`, `UploadedImage`,
  `UploadedFile`, and `Feedback` from the shared mixins in
  `ui_core.db.models_common`, since those tables are schema-identical across
  the web apps.
- `routes/identity.py`, `routes/history.py`, and `routes/feedback.py` are just
  wiring around the shared blueprint factories `ui_core.web.blueprints.identity.make_identity_bp`,
  `...history.make_history_bp`, and `...feedback.make_feedback_bp`.
  `routes/chat.py`, `routes/embed.py`, and `routes/_validation.py` stay
  sandbox-specific — the wizard/context/RAG endpoints have no main_ui
  equivalent.
- `templates/embed.html` extends the shared `ui_core/templates/base_chat.html`.
  CSS is layered the same way: the shared `ui_core/static/css/chat.css` (served
  at `/ui-core/css/chat.css` by `ui_core.web.static_blueprint`) plus sandbox_ui's
  own small `static/css/sandbox-extra.css` override — the teal palette and the
  context-wizard-specific styles.

## What's different

| | `main_ui/` (production) | `sandbox_ui/` (this app) |
| --- | --- | --- |
| Audience | Real OCW students | Developers / TAs |
| Context | Fixed per iframe URL | **Editable in-app** via the "Create context" wizard |
| Syllabus | Always included if present | **Toggleable** per conversation |
| Database | Postgres `asktim` (`DATABASE_URL`) | **Separate Postgres** `asktim_test`, also via `DATABASE_URL` (each Railway service has its own env, so the same var name resolves to a different DB per service) |
| Schema mgmt | Alembic migrations | `Base.metadata.create_all` on boot (throwaway DB) |
| Accent / header | Crimson · Beta+ | `#126f9a` · **Sandbox Beta+** |
| Port | `5001` | `5000` |

Both apps can run side by side.

## The "Create context" wizard

The solid-blue **Edit context** button (top of the sidebar, above "Log in")
opens a step-by-step wizard — internally still called the "Create context"
wizard in code/routes, since it also starts a fresh conversation. The steps
are **Course → Exercise → Tutor → Lectures**, each offering
built-in options from the curriculum:

- **Course** — any folder under `curriculum/`. This step also hosts a **Use RAG
  for course context** toggle (shown only for courses with a built RAG index);
  turning it on retrieves course/lecture material per turn and **skips the Lectures
  step** (the course's pinned material — description, syllabus, guides — is always
  in context via `pinned/*.txt` regardless of mode). The choice is
  stored per conversation in `context_mode` (`rag`/`full_context`; `NULL` = resolve
  by default). The retrieved material always rides in the tutor's **system**
  channel — never on the student's chat turn — since LangChain (langchain-core
  1.4.0) has no "developer" message role. **By default** (cache-friendly
  interleaved history, gated by `TUTOR_CACHED_HISTORY`; see
  [`ui_core/README.md`](../ui_core/README.md#what-the-tutor-receives-each-turn)),
  each turn's retrieved block is its own system message interleaved right after
  that turn's student message, and — because past turns replay byte-identically —
  the whole growing conversation becomes a cacheable prefix, not just the static
  prompt. Under the legacy `TUTOR_CACHED_HISTORY=0` fallback, the retrieved block
  is instead appended after the single static, cacheable prompt as its own
  (uncached) segment: the static prompt keeps its `cache_control` breakpoint
  (Anthropic) / stays the auto-cached prefix (OpenAI), but the per-turn RAG block
  sits after it, re-read at full price each turn. The shared assembly lives in
  `ui_core.tutor_bridge` (`RETRIEVED_CONTEXT_HEADER`) and
  `tutor.cached_history.build_message_plan()` (default) /
  `_build_system_message()` (legacy)
- **Exercise** — an exercise (`exercises/exercise_<NN>.txt`) or a **practice
  problem** (`practices/practice_<NN>.txt`) for the chosen course, shown as
  separate "Exercises" and "Practice problems" groups. The chosen kind is stored
  per conversation in `exercise_kind` (defaults to `exercise`)
- **Tutor** — two controls. The **prompt** dropdown lists every built-in prompt
  for visibility but is **locked to `tutor_06`** (disabled; the routes ignore any
  client-supplied `tutor`, mirroring `main_ui`'s single-prompt lock). Beneath it,
  a **tutor-model** dropdown selects the LLM the tutor runs on — `claude-sonnet-5`
  (default) or `gpt-5.4` — stored per conversation in the `provider` column
  (`claude`/`gpt`; `NULL` = the default, Claude). The prompt dropdown is populated
  from `list_tutors()` in `routes/_validation.py`; the locked value lives in
  `static/js/chat.js` (`LOCKED_TUTOR`) and `DEFAULT_TUTOR`. Provider selection
  (default + coercion of anything unrecognized back to `claude`) is
  `_resolve_provider()` in `ui_core/tutor_bridge.py`, which threads through
  `build_tutor_model` / `create_tutor_graph` and is part of the graph/stream cache key
- **Lectures** — the course's `lectures/*.txt` transcripts (concatenated) or none.
  Uses [`utils.lectures.load_lecture_transcripts`](../utils/lectures.py)

Finishing the wizard **starts a fresh conversation** under the new settings; the
previous chat stays in history. The lectures flag is stored per conversation in
`lectures_enabled`, so reopening a past chat replays it with the same context.
(The course description and syllabus are no longer per-conversation toggles — they
live in `curriculum/<course>/pinned/` and are always folded into context.)

> A simpler **Edit context** modal (built-ins only) previously sat alongside this
> wizard. It was removed in June 2026 because the Create-context wizard offered a
> superset of its functionality. (The Tutor prompt step lists all built-ins but is
> locked to `tutor_06`; see above.)

## Quick start

```powershell
python -m sandbox_ui
```

Binds to `127.0.0.1:5000` by default. Override with the `PORT` env var.

```text
http://127.0.0.1:5000/embed?course=cities_and_climate_change&exercise=01&tutor=tutor_06
```

Health check:

```powershell
curl http://127.0.0.1:5000/health
# {"service":"sandbox_ui","status":"ok"}
```

## Environment variables

`.env` at the repo root is auto-loaded on import.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | — | Required for the tutor LLM call. |
| `ANTHROPIC_API_KEY` | — | Required only if a tutor prompt points at Claude. |
| `SANDBOX_UI_DATABASE_URL` | — | **Preferred.** Postgres URL for the Sandbox's own DB (e.g. `asktim_test`). Set this locally so the Sandbox stays off the `DATABASE_URL` that main_ui uses in the shared `.env`. |
| `DATABASE_URL` | `sqlite:///./sandbox_ui.db` (final fallback) | Used **only if `SANDBOX_UI_DATABASE_URL` is unset**. On Railway each service's env resolves this to its own Postgres, so setting just `DATABASE_URL` on the test service works. Resolution order: `SANDBOX_UI_DATABASE_URL` → `DATABASE_URL` → SQLite `sandbox_ui.db`. |
| `SANDBOX_UI_SECRET_KEY` | `dev-insecure-key` | Flask session signing key. |
| `SANDBOX_UI_COOKIE_SECURE` | `false` | Defaults off so identity/history work over local http. Set `true` behind HTTPS. |
| `SANDBOX_UI_COOKIE_MAX_AGE` | `15552000` (180 days) | Cookie lifetime in seconds. |
| `PORT` | `5000` | TCP port the dev server binds to. |

## Database

No Alembic. On boot, `create_app()` calls `Base.metadata.create_all(engine)`
to build the schema directly from the models into whatever `DATABASE_URL`
points at, then `_reconcile_columns()` backfills any model columns missing from
already-existing tables. By default that's its **own Postgres database**
(`asktim_test`), separate from main_ui's `asktim` so test chats never mix with
production data (falls back to a local SQLite file if the var is unset). The
schema matches `main_ui` plus the sandbox-only `conversations` columns —
`lectures_enabled`, `exercise_kind`, and `context_mode` (the `course_enabled` /
`syllabus_enabled` toggles were retired once that material became pinned, and
`_drop_retired_columns()` clears them from long-lived DBs on boot) — plus the
sandbox-only `messages.retrieved_context` column
(a JSON string of the RAG chunks retrieved for a tutor turn, `NULL` for non-RAG
turns and legacy rows — replayed on later turns to re-render that turn's RAG
block for cache-friendly history) and the `messages.rating` column (integer thumbs vote:
`-1` down / `0` none / `1` up, default `0`, `CHECK (rating IN (-1,0,1))`; only
tutor rows go non-zero, and legacy rows read back `NULL` and are treated as `0`).
It also includes the shared `uploaded_files` table (student CSV/TSV/XLSX/PDF/
DOCX/TXT attachments — bytes, `kind`, and extracted text) and `feedback` table
(`conversation_id`, `turn`, `rating` 1-5, `created_at`); both are brand-new
tables so `create_all` picks them up on boot with no reconcile step needed.

The database must already exist (`CREATE DATABASE asktim_test;`); `create_all`
then builds the tables. To reset the sandbox data, drop and recreate that
database. On startup, `_drop_custom_context_columns(engine)` drops any legacy
`custom_*` columns (from before custom-context was removed) if they exist,
ensuring the schema matches the current model; the drop is idempotent and
runs once per boot.

> **Note:** `create_all` only creates *missing tables* — it never adds columns
> to a table that already exists. To keep the long-lived Sandbox DB usable
> across model changes, `_reconcile_columns()` runs right after `create_all` on
> boot and `ALTER TABLE ... ADD COLUMN`s any model column the existing table
> lacks (nullable, idempotent, race-safe across gunicorn workers) — so a
> new column like `uploaded_images.data` (BYTEA), `lectures_enabled`,
> `messages.retrieved_context`, or `messages.rating` is picked up automatically
> without a manual reset. For the specific case of the
> `uploaded_images.data` column on a very old DB, `python -m
> sandbox_ui.db.reset_uploaded_images` also rebuilds just that table; the
> analogous `python -m sandbox_ui.db.reset_uploaded_files` does the same for
> `uploaded_files`.

> **Design decision (2026-06-04) — DB env-var resolution order.**
> sandbox_ui resolves its database as: **`SANDBOX_UI_DATABASE_URL` → `DATABASE_URL` →
> SQLite `sandbox_ui.db`.**
>
> *Why both names.* It originally read only the prefixed `SANDBOX_UI_DATABASE_URL`
> so that, with both apps loading the *same* root `.env`, you couldn't point the
> Sandbox at the production DB by accident. But the Railway test service was set
> up with a plain `DATABASE_URL` (Railway's default Postgres reference) that the
> app didn't read, so it silently fell back to ephemeral SQLite and "data wasn't
> saving." Briefly unifying on `DATABASE_URL` fixed Railway but then broke *local*
> dev: the shared `.env` has `DATABASE_URL` pointing at main_ui's Postgres, so the
> Sandbox started writing there and hit "column syllabus_enabled does not exist."
>
> *The resolution.* Read `SANDBOX_UI_DATABASE_URL` **first**, fall back to
> `DATABASE_URL`. Best of both: on Railway you can set just `DATABASE_URL` on the
> test service and it works (each service has its own env); locally you set
> `SANDBOX_UI_DATABASE_URL` and the Sandbox stays on its own DB regardless of the
> shared `DATABASE_URL`. `config.py` and `railway-entrypoint-sandbox.sh` both follow
> this order.
>
> **Related reminder:** the Sandbox needs its **own** Postgres. Pointing it at
> main_ui's shared DB is still a bad idea — the two apps would interleave chats —
> but the sandbox-only `conversations` columns (`lectures_enabled`,
> `context_mode`, etc.) no longer *fail* against a main_ui-shaped
> table: `_reconcile_columns()` adds any missing columns on boot.

## API surface

Same as `main_ui` (`/embed`, `/health`, `/api/whoami`, `/api/chat`,
`/api/identity[/check]`, `/api/history`, `/api/conversation/<uuid>`,
`/api/image/<id>`, `/api/feedback` — now dormant, see below), plus:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/context/options` | Courses (with their exercises, practice problems, and syllabus / lectures / RAG availability) and tutor prompts, for the Create-context wizard |
| POST | `/api/message/<id>/rating` | Sets the thumbs vote on a tutor message. JSON body `{"rating": -1\|0\|1}`; verifies the message's conversation is owned by the current session and that the message role is `tutor`; returns `{"ok": true, "rating": N}`, or `400` (bad rating) / `403` (not owned or not a tutor row). Wired from the shared `ui_core.web.blueprints.message_rating.make_message_rating_bp` |

`POST /api/chat` accepts JSON (text only) or `multipart/form-data` (text +
`images` files under the `images` field and non-image attachments — CSV, TSV,
XLSX, PDF, DOCX, TXT — under the new `files` field, alongside the same context
fields). Images and files share a combined cap of 3 attachments per message;
a bad/oversized/unextractable file 400s with `bad_file` / `empty_extraction` /
`extraction_failed` / `too_many_attachments`. It additionally accepts optional
fields for a new conversation:
- `"syllabus": true|false` (defaults to `true`) — gates the syllabus block
- `"lectures": true|false` (defaults to `true`) — gates the lecture-transcripts block
- `"course_enabled": true|false` (defaults to `true`) — gates the course-description block
- `"exercise_kind": "exercise"|"practice"` (defaults to `"exercise"`) — selects exercise or practice-problem variant
- `"context_mode": "rag"|"full_context"` (optional) — per-conversation RAG toggle; omit to let the server resolve by default
- `"tutor"` — **ignored**; the sandbox is locked to `tutor_06` server-side, so any supplied value is discarded

`POST /api/feedback` records a 1-5 star rating against a `conversation_id`
(and optional `turn` number); 400 if `rating`/`conversation_id` are missing or
malformed, 403 if the conversation isn't owned by the current session. This
route (and the `feedback` table behind it) is now **dormant** — it backed the
old mid-conversation star toast, which was replaced by the per-message thumbs
(`POST /api/message/<id>/rating`); the route and table are kept but no longer
exercised by the UI.

`GET /api/conversation/<uuid>` now includes `id` and `rating` on each message in
its payload, so replaying a past conversation restores the thumbs-up/down state
of each tutor message.

The terminal `done` SSE event from `POST /api/chat` also carries
`"tutor_message_id": <int>` — the row id of the just-streamed tutor message — so
the client can immediately rate it via `POST /api/message/<id>/rating`. Since the
Sandbox is a dev/TA tool, `done` additionally carries the tutor's otherwise-hidden
`pedagogical_reasoning` so it can be inspected per message, plus `retrieved` — the
RAG chunks pulled for that turn (`[{source, score, chars, text}]`, or `null`
outside RAG mode). The same `retrieved` records are persisted on the tutor
message row (see [Database](#database)).

## Deployment

**Live on Railway → <https://asktim-sandbox.up.railway.app/>.** The Sandbox
ships as its own Railway service built from `Dockerfile_sandbox`, whose
entrypoint `scripts/railway-entrypoint-sandbox.sh` normalizes the Postgres URL
to the psycopg3 driver, relies on `create_all` (no migration step), and serves
the app with gunicorn (`sandbox_ui.run_app:app`). It runs against its own
`asktim_test` Postgres, separate from `main_ui`'s (see
[`main_ui/README.md`](../main_ui/README.md#deployment-railway)).

To run the Sandbox locally, use `python -m sandbox_ui` (binds to `127.0.0.1:5000`).
Point it at its **own** empty database via `SANDBOX_UI_DATABASE_URL` so it stays
off the `DATABASE_URL` main_ui uses in the shared `.env`.

## Layout

```text
sandbox_ui/
  __main__.py             # python -m sandbox_ui entry point (127.0.0.1, port 5000)
  config.py               # env-driven Config (SANDBOX_UI_* vars, separate DB)
  run_app.py              # ui_core.app_factory.create_app(...) wiring; create_all + _reconcile_columns + _drop_custom_context_columns on boot; blueprints
  cookies.py              # session/username cookie names + kwargs (thin wrapper over ui_core.cookies)
  db/
    models.py             # sandbox-only Conversation (course/syllabus/lectures flags, context_mode) + Message (+ sandbox-only retrieved_context col) / Student / UploadedImage / UploadedFile / Feedback from ui_core.db.models_common
    session.py            # engine + SessionLocal
    reset_uploaded_images.py # one-off: rebuild uploaded_images table (python -m sandbox_ui.db.reset_uploaded_images)
    reset_uploaded_files.py  # one-off: rebuild uploaded_files table (python -m sandbox_ui.db.reset_uploaded_files)
  routes/
    embed.py              # GET /embed, GET / , GET /api/context/options (sandbox-specific)
    chat.py               # POST /api/chat (SSE; syllabus/lectures/course/RAG passthrough, images, files) (sandbox-specific)
    history.py            # GET /api/history, /api/conversation/<uuid> (wraps ui_core.web.blueprints.history)
    identity.py           # GET /api/whoami, POST /api/identity[/check] (wraps ui_core.web.blueprints.identity)
    feedback.py           # POST /api/feedback (wraps ui_core.web.blueprints.feedback)
    _validation.py        # validators + context-option listing helpers
  services/
    conversation.py       # thin wrapper over ui_core.services.conversation (adds the sandbox context flags)
    students.py           # thin wrapper over ui_core.services.students (bcrypt identity)
    images.py             # thin wrapper over ui_core.services.images (validate/persist/serve uploaded images)
    files.py              # thin wrapper over ui_core.services.files (validate/extract/persist non-image attachments)
    feedback.py           # thin wrapper over ui_core.services.feedback (record a 1-5 star rating)
    tutor_bridge.py       # SandboxTutorBridge(ui_core.tutor_bridge.TutorBridge) — overrides cache_key + build_assignment_text for RAG/include-toggle behavior
  static/css/sandbox-extra.css # #126f9a accent + create-context wizard styles, layered on top of ui_core's shared chat.css
  static/js/chat.js       # streaming + sidebar + Create-context wizard
  static/js/marked.min.js # vendored markdown parser (GFM tables)
  static/js/dompurify.min.js # vendored HTML sanitizer (XSS-safe tutor markdown)
  templates/embed.html    # extends ui_core/templates/base_chat.html (Sandbox Beta+, Create context wizard)
```
