# main_ui

Embeddable AskTIM chat app for real MIT OCW students. Designed to load inside an iframe on the course page, with each iframe URL hardcoding its own course + exercise context.

For the overall design — problem framing, schema, identity flow, non-goals — see **Phase 8** of the root [PLANNING.md](../PLANNING.md). For the step-by-step build log, see [main_ui/PLANNING.md](PLANNING.md).

## Status

Steps 1–9 complete. The app is feature-complete for the 2026 Cities and Climate Change deployment minus image uploads (Step 10), a multi-iframe test host page (Step 11), and the formal test suite (Step 12).

What works today:

- iframe-embedded chat at `/embed?course=...&exercise=...&tutor=...`
- Server-Sent Events streaming — tutor replies token-by-token, with hidden `pedagogical-reasoning` server-side
- Postgres-backed persistence (Conversation / Message / Student tables, Alembic migrations)
- Two-stage email + password identity (`/api/identity/check` → `/api/identity`) with bcrypt hashing
- Sidebar with cross-browser conversation history, live-reorder on new turns, click-to-continue past chats
- "Add email" sidebar entry point so students who skipped the modal can come back later
- MIT crimson branding, AskTIM Beta header, "MIT 11.270x Cities and Climate Change" course banner

## Quick start

```powershell
python -m main_ui
```

Binds to `127.0.0.1:5001` by default (avoids clashing with `test_ui/` on `5000`). Override with `PORT` env var.

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

- `conversations` — one per chat thread (UUID PK, session_id, email, course, exercise, tutor)
- `messages` — student/tutor turns (BigInt PK, FK to conversations, role, content, `pedagogical_reasoning`)
- `students` — email + bcrypt password hash for cross-browser identity (one row per email)
- `uploaded_images` — placeholder, used by Step 10
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
| GET | `/api/whoami` | Current session/email state |
| POST | `/api/chat` | Stream a tutor reply as Server-Sent Events |
| POST | `/api/identity/check` | Probe whether an email already has a password registered |
| POST | `/api/identity` | Link the current session to an email by password (signup or verify) |
| GET | `/api/history` | List conversations for the current email cookie |
| GET | `/api/conversation/<uuid>` | Read-only message log for one conversation |

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
  cookies.py              # session + email cookie helpers (HttpOnly, SameSite=None, Partitioned)
  run_app.py              # Flask factory, before/teardown hooks, blueprint registration
  README.md               # this file
  PLANNING.md             # step-by-step build log

  db/
    __init__.py           # re-exports models + session helpers
    models.py             # SQLAlchemy 2.x models: Conversation, Message, Student, UploadedImage
    session.py            # engine + SessionLocal + SQLite PRAGMA foreign_keys=ON hook
    migrations/           # Alembic env + versioned migrations

  routes/
    chat.py               # POST /api/chat (SSE stream, owns its own DB session)
    embed.py              # GET /embed (renders the chat template)
    history.py            # GET /api/history, /api/conversation/<uuid>
    identity.py           # GET /api/whoami, POST /api/identity[/check]
    _validation.py        # shared course/exercise/tutor validators

  services/
    conversation.py       # find/create/append/list/backfill helpers for Conversation+Message
    students.py           # bcrypt create + verify helpers for Student
    tutor_bridge.py       # the one place that talks to tutor.run_tutor

  static/
    css/chat.css          # all chat-page styling
    js/chat.js            # vanilla JS: streaming consumer, sidebar, modal, etc.

  templates/
    embed.html            # iframe-embeddable chat page
```

## How `main_ui/` differs from `test_ui/`

| | `test_ui/` | `main_ui/` |
| --- | --- | --- |
| Audience | Developers / TAs testing tutor configs | Real students embedded in OCW course pages |
| UI | 3-step wizard (tutor, course, exercise) | No wizard — course/exercise come from URL params |
| Persistence | In-memory only | Postgres-backed |
| Identity | None | Email + password, cross-browser via bcrypt |
| Streaming | No | Yes (SSE) |
| Port | `5000` | `5001` |
| Status | Stable — testing harness | Live for the 2026 deployment |

Both apps coexist and can run side by side.

## What's still pending

- **Step 10:** Image uploads (multipart chat, `uploaded_images` rows). Depends on Phase 6 figures-in-tutor-context work.
- **Step 11:** Multi-iframe `test_host.html` for local responsiveness checks.
- **Step 12:** Pytest suite + this README's "production checklist."
