# test_ui — AskTIM Sandbox

Developer/TA **testing website** for the tutor. It mirrors the student-facing
[`main_ui/`](../main_ui/README.md) chat experience — token-streamed replies,
persistent cross-session history, email + password identity — but adds a
**Create context** wizard so a tester can switch course, exercise, tutor prompt,
and syllabus on the fly (picking a built-in or pasting custom text at each step),
and runs against its **own separate database** so test chats never touch
production data.

Branding is deliberately distinct from production: the accent is teal-blue
(`#126f9a`) instead of MIT crimson, and the header reads **AskTIM · Sandbox Beta**.

## What it shares with main_ui

- iframe-style chat at `/embed?course=...&exercise=...&tutor=...` (and a bare `/` that uses defaults)
- Server-Sent Events streaming — tutor replies token-by-token, `pedagogical-reasoning` hidden server-side
- Sanitized-markdown rendering of tutor replies (tables/lists/bold) — `marked` → `DOMPurify`, same `setMessageContent()` path as `main_ui`
- Conversation / Message / Student tables; email + password identity (bcrypt), cross-browser history sidebar
- The same tutor pipeline via `tutor.run_tutor` (through `services/tutor_bridge.py`)
- **Student image uploads** — PNG/JPEG attachments (paperclip or drag-and-drop, up to 5 × 10 MB) sent to the tutor as multimodal input, stored in `uploaded_images.data` (BYTEA) and re-served via `GET /api/image/<id>`. Same shared validation ([`utils/uploads.py`](../utils/uploads.py)) and frontend as `main_ui`

## What's different

| | `main_ui/` (production) | `test_ui/` (this app) |
| --- | --- | --- |
| Audience | Real OCW students | Developers / TAs |
| Context | Fixed per iframe URL | **Editable in-app** via the "Create context" wizard |
| Syllabus | Always included if present | **Toggleable** per conversation |
| Database | Postgres `asktim` (`DATABASE_URL`) | **Separate Postgres** `asktim_test`, also via `DATABASE_URL` (each Railway service has its own env, so the same var name resolves to a different DB per service) |
| Schema mgmt | Alembic migrations | `Base.metadata.create_all` on boot (throwaway DB) |
| Accent / header | Crimson · Beta | `#126f9a` · **Sandbox Beta** |
| Port | `5001` | `5000` |

Both apps can run side by side.

## The "Create context" wizard

The solid-blue **Create context** button (top of the sidebar, above "Add email")
opens a step-by-step wizard. At each step you either pick an existing built-in or
paste your own custom text:

- **Course** — any folder under `curriculum/`, or custom course text
- **Exercise** — an exercise for the chosen course, or custom exercise text
- **Tutor prompt** — any `tutor_*` prompt, or custom prompt text
- **Syllabus** — the course's `syllabus.txt`, none, or custom syllabus text

Finishing the wizard **starts a fresh conversation** under the new settings; the
previous chat stays in history. Custom values are stored per conversation (in the
`custom_*` columns) and the syllabus flag in `syllabus_enabled`, so reopening a
past chat replays it with the same context.

> A simpler **Edit context** modal (built-ins only) previously sat alongside this
> wizard. It was removed in June 2026 because the Create-context wizard does
> everything it did — and also lets you change the tutor prompt and supply custom
> text — so the two buttons were redundant.

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
| `TEST_UI_DATABASE_URL` | — | **Preferred.** Postgres URL for the Sandbox's own DB (e.g. `asktim_test`). Set this locally so the Sandbox stays off the `DATABASE_URL` that main_ui uses in the shared `.env`. |
| `DATABASE_URL` | `sqlite:///./test_ui.db` (final fallback) | Used **only if `TEST_UI_DATABASE_URL` is unset**. On Railway each service's env resolves this to its own Postgres, so setting just `DATABASE_URL` on the test service works. Resolution order: `TEST_UI_DATABASE_URL` → `DATABASE_URL` → SQLite `test_ui.db`. |
| `TEST_UI_SECRET_KEY` | `dev-insecure-key` | Flask session signing key. |
| `TEST_UI_COOKIE_SECURE` | `false` | Defaults off so identity/history work over local http. Set `true` behind HTTPS. |
| `TEST_UI_COOKIE_MAX_AGE` | `15552000` (180 days) | Cookie lifetime in seconds. |
| `PORT` | `5000` | TCP port the dev server binds to. |

## Database

No Alembic. On boot, `create_app()` calls `Base.metadata.create_all(engine)`
to build the schema directly from the models into whatever `DATABASE_URL`
points at. By default that's its **own Postgres database** (`asktim_test`),
separate from main_ui's `asktim` so test chats never mix with production data
(falls back to a local SQLite file if the var is unset). The schema matches
`main_ui` plus a `conversations.syllabus_enabled` column and the
`conversations.custom_*` columns that store one-off custom contexts.

The database must already exist (`CREATE DATABASE asktim_test;`); `create_all`
then builds the tables. To reset the sandbox data, drop and recreate that
database.

> **Note:** `create_all` only creates *missing tables* — it never adds columns
> to existing ones. The image-upload feature added `uploaded_images.data`
> (BYTEA); a pre-existing `asktim_test` DB must be dropped/recreated (or have the
> column added by hand) to pick it up.

> **Design decision (2026-06-04) — DB env-var resolution order.**
> test_ui resolves its database as: **`TEST_UI_DATABASE_URL` → `DATABASE_URL` →
> SQLite `test_ui.db`.**
>
> *Why both names.* It originally read only the prefixed `TEST_UI_DATABASE_URL`
> so that, with both apps loading the *same* root `.env`, you couldn't point the
> Sandbox at the production DB by accident. But the Railway test service was set
> up with a plain `DATABASE_URL` (Railway's default Postgres reference) that the
> app didn't read, so it silently fell back to ephemeral SQLite and "data wasn't
> saving." Briefly unifying on `DATABASE_URL` fixed Railway but then broke *local*
> dev: the shared `.env` has `DATABASE_URL` pointing at main_ui's Postgres, so the
> Sandbox started writing there and hit "column syllabus_enabled does not exist."
>
> *The resolution.* Read `TEST_UI_DATABASE_URL` **first**, fall back to
> `DATABASE_URL`. Best of both: on Railway you can set just `DATABASE_URL` on the
> test service and it works (each service has its own env); locally you set
> `TEST_UI_DATABASE_URL` and the Sandbox stays on its own DB regardless of the
> shared `DATABASE_URL`. `config.py` and `railway-entrypoint-test.sh` both follow
> this order.
>
> **Related reminder:** the Sandbox needs its **own empty** Postgres. Pointing it
> at a main_ui-shaped DB fails — that `conversations` table lacks
> `syllabus_enabled`/`custom_*`, and `create_all` only creates missing *tables*,
> it never adds columns to existing ones.

## API surface

Same as `main_ui` (`/embed`, `/health`, `/api/whoami`, `/api/chat`,
`/api/identity[/check]`, `/api/history`, `/api/conversation/<uuid>`,
`/api/image/<id>`), plus:

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/context/options` | Courses (with their exercises + syllabus availability) and tutor prompts, for the Create-context wizard |

`POST /api/chat` accepts JSON (text only) or `multipart/form-data` (text +
`images` files, alongside the same context fields). It additionally accepts an
optional `"syllabus": true|false` field (defaults to `true`) that gates the
syllabus block for a new conversation.

## Deployment

**Run locally only.** The Sandbox is not currently deployed — its Railway
container (`Dockerfile_test` + `scripts/railway-entrypoint-test.sh`) was removed
because the test deployment isn't working yet, and the work is deferred. Only
`main_ui/` is deployed (see [`main_ui/README.md`](../main_ui/README.md#deployment-railway)).

To run the Sandbox locally, use `python -m test_ui` (binds to `127.0.0.1:5000`).
Point it at its **own** empty database via `TEST_UI_DATABASE_URL` — pointing it at
main_ui's Postgres fails, since that table is missing test_ui's
`syllabus_enabled`/`custom_*` columns and `create_all` won't add them.

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
  static/css/chat.css     # #126f9a accent + create-context wizard styles
  static/js/chat.js       # streaming + sidebar + context switcher
  static/js/marked.min.js # vendored markdown parser (GFM tables)
  static/js/dompurify.min.js # vendored HTML sanitizer (XSS-safe tutor markdown)
  templates/embed.html    # chat page (Sandbox Beta, Create context wizard)
```
