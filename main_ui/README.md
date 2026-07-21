# main_ui

Embeddable AskTIM chat app for real MIT OCW students. Designed to load inside an iframe on the course page, with each iframe URL hardcoding its own course + exercise context.

**🔗 Live: <https://asktim.up.railway.app/>**

For the overall design — problem framing, schema, identity flow, non-goals — see **Phase 8** of the root [PLANNING.md](../PLANNING.md). For the step-by-step build log, see [main_ui/PLANNING.md](PLANNING.md).

## Status

Steps 1–10 complete and **deployed on Railway** (containerized via the root `Dockerfile_main` + `scripts/railway-entrypoint-main.sh` — see [Deployment](#deployment-railway)). The app is feature-complete for the 2026 Cities and Climate Change deployment minus a multi-iframe test host page (Step 11) and the formal test suite (Step 12).

What works today:

- iframe-embedded chat at `/embed?course=...&exercise=...&tutor=...`
- Server-Sent Events streaming — tutor replies token-by-token, with hidden `pedagogical-reasoning` server-side
- Sanitized-markdown rendering of tutor replies — tables, lists, and bold display cleanly (`marked` → `DOMPurify`, vendored locally under `static/js/`; rendered on stream completion; falls back to plain text if the libs don't load)
- Postgres-backed persistence (Conversation / Message / Student tables, Alembic migrations)
- Two-stage username + password identity (`/api/identity/check` → `/api/identity`) with bcrypt hashing
- Sidebar with cross-browser conversation history, live-reorder on new turns, click-to-continue past chats
- "Log in" sidebar entry point (button text + tooltip) so students who skipped the modal can come back later
- MIT crimson branding, AskTIM Beta+ header, "MIT 11.270x Cities and Climate Change" course banner
- Per-course lecture transcripts (`curriculum/<course>/lectures/*.txt`) auto-folded into tutor context when present (text-only, no-op until a course adds them) — via [`utils.lectures`](../utils/lectures.py)
- **Paired solution as tutor-only reference** — when the exercise has a matching solution file, its "correct answer & worked solution" is injected right after the exercise for the tutor only (via [`utils.curriculum.read_solution`](../utils/curriculum.py)); it's deterministic (keyed by problem number), never revealed to the student, and no-op for exercises with no solution file
- **Curriculum figures** auto-attached to the tutor: any `curriculum/<course>/figures/exercise_<NN>_*.{png,jpg,jpeg}` matching the conversation's exercise is sent to the tutor as multimodal input on every turn (re-attached each call since per-call history is text-only) — via [`utils.figures.discover_figures`](../utils/figures.py) in [`services/tutor_bridge.py`](services/tutor_bridge.py); no-op for exercises with no figure
- **Student image uploads** (Step 10): the composer accepts PNG/JPEG attachments (paperclip, drag-and-drop, or clipboard paste, up to 5 × 10 MB), streamed to the tutor as multimodal input on that turn. Bytes are stored in-DB (`uploaded_images.data`, BYTEA) so they survive Railway redeploys, re-rendered in history via `GET /api/image/<id>`. Validation is shared with `sandbox_ui` in [`utils/uploads.py`](../utils/uploads.py); images attach only to the turn they're sent on (prior turns stay text-only). Clicking any chat image — a staged composer thumbnail or one already sent — opens it enlarged and centered in a lightbox (backdrop / × / Esc to close)
- **Non-image file attachments**: the composer also accepts CSV, TSV, XLSX, PDF, DOCX, and TXT (paperclip, drag-and-drop, or clipboard paste), shown as a file-icon chip. Files and images share one combined cap of 3 attachments per message ([`utils/uploads.py`](../utils/uploads.py) `enforce_combined_cap`). Each file is validated and text-extracted server-side by [`utils/attachments.py`](../utils/attachments.py) (5 MB per-file cap, 15000-char combined extracted-text budget, truncated with a marker past that) via [`services/files.py`](services/files.py); bytes + extracted text are stored in-DB (`uploaded_files`, added by the `eb96d85f90cf` migration) and the extracted text is re-injected into the tutor's history on every later turn, so file context persists across the conversation (the student-facing message stays the plain filename/text)
- **Per-message thumbs up/down**: each tutor message renders a thumbs-up / thumbs-down control below its bubble. Clicking sets the message's rating (up / down); clicking the active thumb again clears it back to neutral. Submits to `POST /api/message/<id>/rating`, persisted to the `messages.rating` column (added by the `f1a2b3c4d5e6` migration). This replaces the old mid-conversation 1-5 star feedback toast; the legacy `feedback` table and `POST /api/feedback` route are kept but dormant
- **KaTeX math rendering**: tutor replies render `\(...\)` / `\[...\]` LaTeX with a vendored KaTeX 0.16.11 (`$...$` is deliberately left alone as currency), via the shared `renderTutorMarkdown` helper in [`ui_core/static/js/katex-marked.js`](../ui_core/static/js/katex-marked.js)

## Architecture

`main_ui/` is a thin shell over the shared [`ui_core/`](../ui_core/) package, which also backs [`sandbox_ui/`](../sandbox_ui/). `run_app.py` builds the Flask app via `ui_core.app_factory.create_app(...)` — one factory owns `SECRET_KEY` setup, the session-id/db-session before/teardown hooks, the session-cookie `after_request`, `/health`, and blueprint registration, so the two apps no longer duplicate that plumbing.

- `services/{conversation,students,images}.py` are thin wrappers binding main_ui's own model classes to the shared, app-agnostic logic in `ui_core.services.*`; `services/tutor_bridge.py` wraps a single `ui_core.tutor_bridge.TutorBridge()` instance. **Per-turn RAG is the default context mode** for all shipped courses; when RAG retrieval yields no results, both apps fail closed with an error banner and `TUTOR_CONTEXT_MODE=full_context` is the escape hatch — see [`rag/README.md`](../rag/README.md#mandatory-rag-fail-closed).
- `db/models.py` keeps main_ui's own `Conversation` (its schema is the minimal one — sandbox_ui's adds columns) but gets `Message`, `Student`, and `UploadedImage` from mixins in `ui_core.db.models_common`; `db/session.py` and `cookies.py` are thin wrappers over `ui_core.db.session` / `ui_core.cookies`.
- `routes/identity.py` and `routes/history.py` are built from shared blueprint factories — `ui_core.web.blueprints.identity.make_identity_bp` and `.history.make_history_bp` — parameterized with main_ui's own `cookies`/`services` modules. `routes/{chat,embed,_validation}.py` remain main_ui-specific.
- The page template `templates/embed.html` is just `{% extends "base_chat.html" %}`, pulling in the shared shell at [`ui_core/templates/base_chat.html`](../ui_core/templates/base_chat.html). The stylesheet is served from the shared `ui_core` static blueprint at `/ui-core/css/chat.css` (source: [`ui_core/static/css/chat.css`](../ui_core/static/css/chat.css)) — main_ui's own `static/` now holds only `js/`.

## Quick start

```powershell
python -m main_ui
```

Binds to `127.0.0.1:5001` by default. Override with the `PORT` env var.

Open the chat in a browser:

```text
http://127.0.0.1:5001/embed?course=cities_and_climate_change&exercise=01
```

Production is **locked to `tutor_07`** — `DEFAULT_TUTOR` in
[`routes/_validation.py`](routes/_validation.py) is forced at both the embed and
chat entry points, so a `?tutor=` query param is ignored.

Verify the server is up:

```powershell
curl http://127.0.0.1:5001/health
# {"service":"main_ui","status":"ok"}
```

## Environment variables

`.env` at the repo root is auto-loaded on import (see [`__init__.py`](__init__.py)).

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | — | Required — the tutor runs on Claude (Sonnet 5) by default. |
| `OPENAI_API_KEY` | — | Required — RAG embeddings (`text-embedding-3-small`) and the Sandbox's optional `gpt-5.4` tutor. |
| `DATABASE_URL` | `sqlite:///./main_ui.db` | Postgres URL recommended for real use. Example: `postgresql+psycopg://postgres:PASSWORD@localhost:5432/asktim`. |
| `MAIN_UI_SECRET_KEY` | `dev-insecure-key` | Flask session signing key. Replace in production. |
| `MAIN_UI_COOKIE_SECURE` | `true` | Set to `false` for non-HTTPS local testing if cookies aren't sticking. |
| `MAIN_UI_COOKIE_MAX_AGE` | `15552000` (180 days) | Cookie lifetime in seconds. |
| `PORT` | `5001` | TCP port the Flask dev server binds to. |

## Database

Schema is managed with Alembic. Migrations live in [db/migrations/versions/](db/migrations/versions/).

```powershell
# From repo root — create or update the asktim database
python -m alembic -c main_ui\db\migrations\alembic.ini upgrade head
```

Seven tables in `public`:

- `conversations` — one per chat thread (UUID PK, session_id, username, course, exercise_number, tutor_prompt)
- `messages` — student/tutor turns (BigInt PK, FK to conversations, role, content, `pedagogical_reasoning`, `rating` — integer thumbs rating, `-1` down / `0` none / `1` up, default `0`, CHECK `rating IN (-1,0,1)`; legacy rows read `NULL` and are treated as `0`; `cost_usd` — nullable float, the estimated USD cost of producing a tutor turn (`NULL` on student rows and pre-feature rows), with its model-id + token breakdown in `usage_json` (nullable text); `retrieved_context` — nullable text, a JSON string of the RAG chunks retrieved for a tutor turn, `NULL` for non-RAG turns and pre-migration rows, added by the `c9f1a2b3d4e5` migration — persisted so cache-friendly history can re-render each prior turn's RAG block deterministically on replay)
- `students` — username + bcrypt password hash for cross-browser identity (one row per username)
- `uploaded_images` — student-uploaded images: `filename`, `mime_type`, `size_bytes`, and `data` (BYTEA bytes), FK to the student `messages` row
- `uploaded_files` — student-uploaded non-image attachments: `filename`, `kind`, `extracted_text`, `size_bytes`, and `data` (raw bytes), FK to the student `messages` row
- `feedback` — legacy 1-5 star ratings (dormant, superseded by `messages.rating`): `conversation_id` (FK, cascade), nullable `turn`, `rating` (CHECK 1..5), `created_at`
- `alembic_version` — Alembic bookkeeping

Inspect data with psql or pgAdmin:

```powershell
$env:PGPASSWORD = '<your-postgres-password>'
psql -U postgres -h localhost -d asktim -c "SELECT turn, role, LEFT(content, 60) FROM messages ORDER BY id DESC LIMIT 10;"
```

## API surface

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/embed` | Render the chat page (params: `course`, `exercise`, `tutor`) |
| GET | `/health` | Liveness probe |
| GET | `/api/whoami` | Current session/username state |
| POST | `/api/chat` | Stream a tutor reply as Server-Sent Events. JSON (text only) or `multipart/form-data` (text + `images` files + `files` non-image attachments) |
| POST | `/api/identity/check` | Probe whether a username already has a password registered |
| POST | `/api/identity` | Link the current session to a username by password (signup or verify) |
| GET | `/api/history` | List conversations for the current username cookie |
| GET | `/api/conversation/<uuid>` | Read-only message log for one conversation (each message includes its `id`, `rating`, and any `images`/`files` metadata) |
| GET | `/api/image/<id>` | Serve an uploaded image's bytes (ownership-checked by session/username; 404 otherwise) |
| POST | `/api/message/<id>/rating` | Set a tutor message's thumbs rating (JSON: `{"rating": -1\|0\|1}`; ownership-checked + tutor-only; returns `{"ok": true, "rating": N}`) |
| POST | `/api/feedback` | **Dormant** (kept, superseded by `/api/message/<id>/rating`): record a 1-5 star rating for a conversation (JSON: `conversation_id`, `rating`, optional `turn`) |

### Streaming chat shape

`POST /api/chat` returns `text/event-stream` after pre-stream validation (validation errors still come back as JSON 400/403/404):

```text
event: delta
data: {"text": "Urban "}

event: delta
data: {"text": "heat "}
...
event: done
data: {"conversation_id": "...", "reply": "Urban heat island refers to...", "student_message_count": 3, "tutor_message_id": 42}
```

The `done` event's `tutor_message_id` is the DB id of the freshly persisted tutor row, used by the client to target `POST /api/message/<id>/rating` for the thumbs control. Mid-stream failure emits a final `error` frame, never an incomplete tutor row in the DB.

## Layout

```text
main_ui/
  __init__.py             # package marker + .env auto-load
  __main__.py             # python -m main_ui entry point
  config.py               # env-driven Config dataclass
  cookies.py              # thin wrapper over ui_core.cookies (adds main_ui's secure/max-age config)
  run_app.py              # builds the app via ui_core.app_factory.create_app(...)
  README.md               # this file
  PLANNING.md             # step-by-step build log

  db/
    __init__.py           # re-exports models + session helpers
    models.py             # Conversation (main_ui's own schema); Message/Student/UploadedImage via ui_core.db.models_common mixins
    session.py            # thin wrapper over ui_core.db.session (engine + SessionLocal)
    migrations/           # Alembic env + versioned migrations

  routes/
    chat.py               # POST /api/chat (SSE stream, owns its own DB session) — main_ui-specific
    embed.py              # GET /embed (renders the chat template) — main_ui-specific
    history.py            # GET /api/history, /api/conversation/<uuid> — built from ui_core.web.blueprints.history
    identity.py           # GET /api/whoami, POST /api/identity[/check] — built from ui_core.web.blueprints.identity
    feedback.py           # POST /api/feedback (dormant) — built from ui_core.web.blueprints.feedback
    message_rating.py     # POST /api/message/<id>/rating — built from ui_core.web.blueprints.message_rating
    _validation.py        # shared course/exercise/tutor validators — main_ui-specific

  services/
    conversation.py       # thin wrapper binding Conversation/Message to ui_core.services.conversation
    students.py           # thin wrapper binding Student to ui_core.services.students
    images.py             # thin wrapper binding UploadedImage to ui_core.services.images
    files.py              # thin wrapper binding UploadedFile to ui_core.services.files (non-image attachments)
    feedback.py           # thin wrapper binding Feedback to ui_core.services.feedback
    tutor_bridge.py       # thin wrapper around one shared ui_core.tutor_bridge.TutorBridge()

  static/
    js/chat.js            # vanilla JS: streaming consumer, sidebar, modal, etc.
    js/marked.min.js      # vendored markdown parser (GFM tables) — tutor message rendering
    js/dompurify.min.js   # vendored HTML sanitizer — XSS-safe innerHTML for tutor markdown

  templates/
    embed.html            # {% extends "base_chat.html" %} — the shared chat shell lives in ui_core/templates/
```

## Deployment (Railway)

`main_ui/` is the only app packaged for production. Container build and process
config live at the repo root:

- [`Dockerfile_main`](../Dockerfile_main) — Python 3.12-slim image; installs `libpq5` + `requirements.txt`, copies only the runtime packages (`main_ui/`, `tutor/`, `curriculum/`, `utils/`) plus the entrypoint, exposes `5001`, and registers a `/health` HEALTHCHECK.
- [`Procfile`](../Procfile) — `web: gunicorn main_ui.run_app:app --bind 0.0.0.0:$PORT`.
- [`scripts/railway-entrypoint-main.sh`](../scripts/railway-entrypoint-main.sh) — container entrypoint: validates `OPENAI_API_KEY`, **normalizes the `DATABASE_URL` scheme to `postgresql+psycopg://`** (Railway hands out bare `postgres://`, but the app ships psycopg3 only), runs `alembic upgrade head`, then `exec`s gunicorn with `WEB_CONCURRENCY` workers and a `GUNICORN_TIMEOUT`.

The WSGI entrypoint is `main_ui.run_app:app`. Production reads `DATABASE_URL`
from the Railway Postgres service; migrations run automatically on every boot.

## How `main_ui/` relates to `sandbox_ui/`

`main_ui/` is the student-facing production app: course/exercise/tutor come from
URL params, conversations persist to PostgreSQL (`asktim`), identity is username +
password (bcrypt, cross-browser), and replies stream over SSE.

[`sandbox_ui/`](../sandbox_ui/README.md) ("AskTIM Sandbox") is the developer/TA
counterpart. It reuses the same chat UI and tutor pipeline but lets testers
change context **in the app** rather than via URL params, through a **Create
context** wizard: pick a built-in course/exercise/tutor-prompt/syllabus or paste
one-off custom text at each step.
It runs on its **own** PostgreSQL database (`asktim_test`) so test chats never
mix with production data, builds its schema with `create_all` (no Alembic), and
uses a teal-blue (`#126f9a`) accent instead of crimson. Both apps can run side
by side (`main_ui` on `5001`, `sandbox_ui` on `5000`).

Both apps are thin shells over the shared [`ui_core/`](../ui_core/) package —
see [Architecture](#architecture) above — which is where the Flask app
factory, DB/cookie/session plumbing, identity + history blueprints, the tutor
bridge, and the base chat template/stylesheet actually live.

## What's still pending

- **Step 11:** Multi-iframe `test_host.html` for local responsiveness checks.
- **Step 12:** Pytest suite + this README's "production checklist."

> **Step 10 (image uploads) is done.** The streaming path now carries multimodal
> student turns; uploads are validated ([`utils/uploads.py`](../utils/uploads.py)),
> stored in `uploaded_images.data` (BYTEA), and re-served via `GET /api/image/<id>`.
> Apply the migration on deploy: `alembic upgrade head` (revision
> `b7c4e1a9d2f0`) — the entrypoint runs this automatically on Railway boot.

> **Non-image file attachments and (legacy) star-rating feedback are done.** Two more
> migrations ship with these: `eb96d85f90cf` (`uploaded_files` table) and
> `a7f3c1e9b204` (`feedback` table) — both applied automatically by
> `alembic upgrade head` on Railway boot, same as above.

> **Per-message thumbs ratings are done.** The `f1a2b3c4d5e6` migration
> (down_revision `a7f3c1e9b204`) adds the `messages.rating` column and
> supersedes the star-rating toast — applied automatically by
> `alembic upgrade head` on Railway boot. The `feedback` table and
> `POST /api/feedback` route are kept but dormant.

> **Cache-friendly interleaved history is now the default tutor path.** The
> `c9f1a2b3d4e5` migration (down_revision `a1b2c3d4e5f6`) adds the nullable
> `messages.retrieved_context` column so per-turn RAG can be replayed
> deterministically. Gated by `TUTOR_CACHED_HISTORY` (default ON); set it to
> `0`/`false`/`no`/`off` to fall back to the legacy single-system-message path.
> See [`tutor/README.md`](../tutor/README.md#prompt-caching) and
> [`ui_core/README.md`](../ui_core/README.md#what-the-tutor-receives-each-turn)
> for the full request-shape/caching details.
