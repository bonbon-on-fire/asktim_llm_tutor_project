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
- MIT crimson branding, AskTIM Beta header, "MIT 11.270x Cities and Climate Change" course banner
- Per-course lecture transcripts (`curriculum/<course>/lectures/*.txt`) auto-folded into tutor context when present (text-only, no-op until a course adds them) — via [`utils.lectures`](../utils/lectures.py)
- **Curriculum figures** auto-attached to the tutor: any `curriculum/<course>/figures/exercise_<NN>_*.{png,jpg,jpeg}` matching the conversation's exercise is sent to the tutor as multimodal input on every turn (re-attached each call since per-call history is text-only) — via [`utils.figures.discover_figures`](../utils/figures.py) in [`services/tutor_bridge.py`](services/tutor_bridge.py); no-op for exercises with no figure
- **Student image uploads** (Step 10): the composer accepts PNG/JPEG attachments (paperclip, drag-and-drop, or clipboard paste, up to 5 × 10 MB), streamed to the tutor as multimodal input on that turn. Bytes are stored in-DB (`uploaded_images.data`, BYTEA) so they survive Railway redeploys, re-rendered in history via `GET /api/image/<id>`. Validation is shared with `sandbox_ui` in [`utils/uploads.py`](../utils/uploads.py); images attach only to the turn they're sent on (prior turns stay text-only). Clicking any chat image — a staged composer thumbnail or one already sent — opens it enlarged and centered in a lightbox (backdrop / × / Esc to close)

## Architecture

`main_ui/` is a thin shell over the shared [`ui_core/`](../ui_core/) package, which also backs [`sandbox_ui/`](../sandbox_ui/). `run_app.py` builds the Flask app via `ui_core.app_factory.create_app(...)` — one factory owns `SECRET_KEY` setup, the session-id/db-session before/teardown hooks, the session-cookie `after_request`, `/health`, and blueprint registration, so the two apps no longer duplicate that plumbing.

- `services/{conversation,students,images}.py` are thin wrappers binding main_ui's own model classes to the shared, app-agnostic logic in `ui_core.services.*`; `services/tutor_bridge.py` wraps a single `ui_core.tutor_bridge.TutorBridge()` instance.
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
http://127.0.0.1:5001/embed?course=cities_and_climate_change&exercise=01&tutor=tutor_05
```

Verify the server is up:

```powershell
curl http://127.0.0.1:5001/health
# {"service":"main_ui","status":"ok"}
```

## Environment variables

`.env` at the repo root is auto-loaded on import (see [`__init__.py`](__init__.py)).

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | — | Required for the tutor LLM call. |
| `ANTHROPIC_API_KEY` | — | Required only if you point a tutor prompt at Claude. |
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

Five tables in `public`:

- `conversations` — one per chat thread (UUID PK, session_id, username, course, exercise_number, tutor_prompt)
- `messages` — student/tutor turns (BigInt PK, FK to conversations, role, content, `pedagogical_reasoning`)
- `students` — username + bcrypt password hash for cross-browser identity (one row per username)
- `uploaded_images` — student-uploaded images: `filename`, `mime_type`, `size_bytes`, and `data` (BYTEA bytes), FK to the student `messages` row
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
| POST | `/api/chat` | Stream a tutor reply as Server-Sent Events. JSON (text only) or `multipart/form-data` (text + `images` files) |
| POST | `/api/identity/check` | Probe whether a username already has a password registered |
| POST | `/api/identity` | Link the current session to a username by password (signup or verify) |
| GET | `/api/history` | List conversations for the current username cookie |
| GET | `/api/conversation/<uuid>` | Read-only message log for one conversation (each message includes any `images` metadata) |
| GET | `/api/image/<id>` | Serve an uploaded image's bytes (ownership-checked by session/username; 404 otherwise) |

### Streaming chat shape

`POST /api/chat` returns `text/event-stream` after pre-stream validation (validation errors still come back as JSON 400/403/404):

```text
event: delta
data: {"text": "Urban "}

event: delta
data: {"text": "heat "}
...
event: done
data: {"conversation_id": "...", "reply": "Urban heat island refers to...", "student_message_count": 3}
```

Mid-stream failure emits a final `error` frame, never an incomplete tutor row in the DB.

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
    _validation.py        # shared course/exercise/tutor validators — main_ui-specific

  services/
    conversation.py       # thin wrapper binding Conversation/Message to ui_core.services.conversation
    students.py           # thin wrapper binding Student to ui_core.services.students
    images.py             # thin wrapper binding UploadedImage to ui_core.services.images
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
