# test_ui — AskTIM Sandbox

Developer/TA **testing website** for the tutor. It mirrors the student-facing
[`main_ui/`](../main_ui/README.md) chat experience — token-streamed replies,
persistent cross-session history, email + password identity — but adds an
**Edit context** switcher so a tester can change course, exercise, tutor prompt,
and the syllabus toggle on the fly, and runs against its **own separate
database** so test chats never touch production data.

Branding is deliberately distinct from production: the accent is teal-blue
(`#126f9a`) instead of MIT crimson, and the header reads **AskTIM · Sandbox Beta**.

## What it shares with main_ui

- iframe-style chat at `/embed?course=...&exercise=...&tutor=...` (and a bare `/` that uses defaults)
- Server-Sent Events streaming — tutor replies token-by-token, `pedagogical-reasoning` hidden server-side
- Conversation / Message / Student tables; email + password identity (bcrypt), cross-browser history sidebar
- The same tutor pipeline via `tutor.run_tutor` (through `services/tutor_bridge.py`)

## What's different

| | `main_ui/` (production) | `test_ui/` (this app) |
| --- | --- | --- |
| Audience | Real OCW students | Developers / TAs |
| Context | Fixed per iframe URL | **Editable in-app** via the "Edit context" button |
| Syllabus | Always included if present | **Toggleable** per conversation |
| Database | Shared Postgres (`DATABASE_URL`) | **Separate** (`TEST_UI_DATABASE_URL`, SQLite by default) |
| Schema mgmt | Alembic migrations | `Base.metadata.create_all` on boot (throwaway DB) |
| Accent / header | Crimson · Beta | `#126f9a` · **Sandbox Beta** |
| Port | `5001` | `5000` |

Both apps can run side by side.

## The "Edit context" switcher

The solid-blue **Edit context** button (top of the sidebar, above "Add email")
opens a modal to choose:

- **Course** — any folder under `curriculum/`
- **Exercise** — exercises available for the chosen course
- **Tutor prompt** — `tutor_01`–`tutor_05`
- **Include course syllabus** — folds `syllabus.txt` into the tutor context (disabled for courses that have none)

Applying a change **starts a fresh conversation** under the new settings; the
previous chat stays in history. The chosen syllabus flag is stored per
conversation, so reopening a past chat replays it with the same context.

## Quick start

```powershell
python -m test_ui
```

Binds to `127.0.0.1:5000` by default. Override with the `PORT` env var.

```text
http://127.0.0.1:5000/embed?course=cities_and_climate_change&exercise=01&tutor=tutor_05
```

Health check:

```powershell
curl http://127.0.0.1:5000/health
# {"service":"test_ui","status":"ok"}
```

## Environment variables

`.env` at the repo root is auto-loaded on import.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | — | Required for the tutor LLM call. |
| `ANTHROPIC_API_KEY` | — | Required only if a tutor prompt points at Claude. |
| `TEST_UI_DATABASE_URL` | `sqlite:///./test_ui.db` | Separate from main_ui's `DATABASE_URL` so test data stays isolated. |
| `TEST_UI_SECRET_KEY` | `dev-insecure-key` | Flask session signing key. |
| `TEST_UI_COOKIE_SECURE` | `false` | Defaults off so identity/history work over local http. Set `true` behind HTTPS. |
| `TEST_UI_COOKIE_MAX_AGE` | `15552000` (180 days) | Cookie lifetime in seconds. |
| `PORT` | `5000` | TCP port the dev server binds to. |

## Database

No Alembic. On boot, `create_app()` calls `Base.metadata.create_all(engine)`
to build the schema directly from the models into whatever `TEST_UI_DATABASE_URL`
points at (a local SQLite file by default). The schema matches `main_ui` plus a
`conversations.syllabus_enabled` column that records the syllabus toggle.

To reset the sandbox data, just delete the SQLite file (`test_ui.db`).

## API surface

Same as `main_ui` (`/embed`, `/health`, `/api/whoami`, `/api/chat`,
`/api/identity[/check]`, `/api/history`, `/api/conversation/<uuid>`), plus:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/context/options` | Courses (with their exercises + syllabus availability) and tutor prompts, for the Edit-context switcher |

`POST /api/chat` additionally accepts an optional `"syllabus": true|false` field
(defaults to `true`) that gates the syllabus block for a new conversation.

## Layout

```text
test_ui/
  __main__.py             # python -m test_ui entry point (port 5000)
  config.py               # env-driven Config (TEST_UI_* vars, separate DB)
  run_app.py              # Flask factory; create_all on boot; blueprints
  db/                     # SQLAlchemy models (+ syllabus_enabled) and session
  routes/
    embed.py              # GET /embed, GET / , GET /api/context/options
    chat.py               # POST /api/chat (SSE, syllabus passthrough)
    history.py            # GET /api/history, /api/conversation/<uuid>
    identity.py           # GET /api/whoami, POST /api/identity[/check]
    _validation.py        # validators + context-option listing helpers
  services/
    conversation.py       # persistence (stores syllabus_enabled)
    students.py           # bcrypt identity
    tutor_bridge.py       # talks to tutor.run_tutor (include_syllabus aware)
  static/css/chat.css     # #126f9a accent + context-modal styles
  static/js/chat.js       # streaming + sidebar + context switcher
  templates/embed.html    # chat page (Sandbox Beta, Edit context modal)
```
