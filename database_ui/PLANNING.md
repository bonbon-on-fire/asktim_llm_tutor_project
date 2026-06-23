# Plan: `database_ui` — read-only conversation review for AskTIM

> Status: **live on Railway** at <https://asktim-database.up.railway.app/> (service
> `askTIM-database`, password-gated, reading askTIM-main's Postgres read-only).
> Action item from the 06/16 meeting: "Build a small interface for reviewing real
> AskTIM conversation data." Phases 1–7 complete and deployed.
>
> Shipped UI differs slightly from the original plan below: the date/student sort
> toggle was dropped (list is most-recent-first, each row labeled by student
> email), the login is a modal over a dimmed backdrop, the top bar is an empty
> thin strip with a sidebar open/close toggle, and rows tint crimson on hover.

## Goal

A read-only dashboard for browsing **all** real conversations in **`main_ui`'s
production database** (the Postgres `humanities-main` references). A single
Railway service, styled to match `main_ui` (MIT crimson), titled
**"AskTIM · Database Beta"**.

It looks like the real `main_ui` chat site (the sidebar + transcript view), but
with the chat composer and action buttons removed and an all-students
conversation list.

> Scope note: an earlier draft planned a second deployment to also review the
> `sandbox_ui` Sandbox DB. Current scope is **main_ui only**. The code stays generic
> enough (DB + title + accent are env vars) that a Sandbox review could be added
> later as a second deployment if wanted.

## Decisions locked

- **Identity = email.** There is no "student ID" column; the only identity
  carrier is `email` (nullable) plus an opaque `session_id`. The review UI
  groups/sorts by email and shows it above each conversation row; anonymous
  sessions (no email) fall back to a muted `Anonymous` / short `session_id`.
- **One read-only app for main_ui.** Single Railway service reading the main_ui
  Postgres.
- **Looks like main_ui.** Same MIT crimson accent (`#8c1a1b`); title
  "AskTIM · Database Beta".

## Architecture note that shapes everything

The review app defines its **own minimal, read-only model** over only these
columns (which are exactly `main_ui.conversations`'s columns):

`id, session_id, email, course, exercise_number, tutor_prompt, started_at,
last_active_at` + `messages` + `uploaded_images`.

Keeping it to this shared subset (no `sandbox_ui`-only `syllabus_enabled` /
`custom_*` / `context_mode`) means the same model would also read the Sandbox DB
unchanged — leaving the door open for a future Sandbox deployment without a
schema fork.

## Connecting to the Railway DB

Same pattern the live apps already use: read a connection string and open a
SQLAlchemy engine (cf. `sandbox_ui/config.py`). The review app issues **read-only**
queries against the same DB.

**On Railway** (no secrets copied around):

1. Add a **new service** in the `tutors (UW, humanities)` project from this repo.
2. Give it a **reference variable** to share the main_ui Postgres over the
   private network: `DATABASE_UI_DATABASE_URL = ${{<main Postgres>.DATABASE_URL}}`
   (the Postgres `humanities-main` references).
3. Service boots, reads the URL, queries. No new schema, no `create_all`.

**Local run against prod** (quick review without deploying): use the **public**
URL — `<main Postgres> → Variables → DATABASE_PUBLIC_URL` (the `...proxy.rlwy.net`
host). The internal `*.railway.internal` host only resolves inside Railway.

## Repo structure (new top-level package)

```
database_ui/
  __init__.py
  __main__.py
  run_app.py            # Flask app factory; read-only engine from DATABASE_UI_DATABASE_URL
  config.py             # DATABASE_UI_DATABASE_URL, DATABASE_UI_TITLE, DATABASE_UI_ACCENT, DATABASE_UI_PASSWORD, port
  auth.py               # shared-password gate (login form + session check)
  db/
    models.py           # minimal read-only models (common columns only)
    session.py          # engine + Session (echo off, NO create_all)
  services/
    conversations.py    # list_all_conversations(), get_conversation(), get_image()
  routes/
    database.py           # endpoints below
  static/               # adapted main_ui chat.css + trimmed chat.js
  templates/
    index.html          # adapted from main_ui shell; injects title
    login.html
README.md               # run/env/deploy notes
PLANNING.md             # this document
```

## Backend endpoints (all read-only, all behind auth)

- `GET /` → app shell (redirect to `/login` if not authed).
- `GET /login`, `POST /login` → shared-password gate; sets a signed session cookie.
- `GET /api/conversations` → **the new piece.** Lists *all* conversations (no
  email scoping, unlike the live email-scoped history). Per row: `id, email,
  course, exercise_number, started_at, last_active_at, message_count`. Supports
  `?sort=date|student` and pagination (`?limit=&offset=`).
- `GET /api/conversation/<uuid>` → full transcript (mirrors the live detail
  endpoint, **without** the ownership check — review sees everything).
- `GET /api/image/<int>` → serve uploaded image bytes (ownership check dropped).

## Frontend (reuse main_ui's chat UI, stripped)

Start from **`main_ui`** templates/JS (the app being reviewed) so it looks
identical, then:

- **Remove** the entire chat composer bar ("Ask anything" text field + attach/paperclip + send button), plus **Edit context** and **New chat** — the page is purely for reading, no input affordances at all.
- **Header + tab title** from `DATABASE_UI_TITLE` (`AskTIM · Database Beta`).
- **Sidebar list** driven by `/api/conversations`:
  - Sort by **date** (default) and by **student (email)**.
  - Each item shows the **email on a line above** the existing
    `Exercise 1 · Jun 15 · N messages` line; muted `Anonymous` when null.
  - When sorted by student, group rows under each email header.
- **Clicking** a row loads the read-only transcript (reuse the existing message
  renderer: tutor pedagogical-reasoning + inline images).

## Look (matches main_ui)

Styled to match `main_ui` — same MIT crimson accent (`#8c1a1b`, hover `#6f1414`),
the same `chat.css` variables. No theme switching; the accent is fixed to
main_ui's. `DATABASE_UI_ACCENT` exists only as an optional override.

| Var | Value |
| --- | --- |
| `DATABASE_UI_DATABASE_URL` | `${{<main Postgres>.DATABASE_URL}}` (humanities-main's DB) |
| `DATABASE_UI_TITLE` | `AskTIM · Database Beta` |
| `DATABASE_UI_ACCENT` (optional) | defaults to `#8c1a1b` (MIT crimson, = main_ui) |
| `DATABASE_UI_PASSWORD` | shared secret (required for deploy) |
| `DATABASE_UI_SECRET_KEY` | session signing |

## Railway deployment

- New `Dockerfile_database` (copy of `Dockerfile_main`): `COPY database_ui/` +
  `utils/`; **no** `tutor/`, `rag/`, or `curriculum/` (review doesn't run the
  tutor). gunicorn target `database_ui.run_app:app`.
- New `scripts/railway-entrypoint-database.sh`: normalize the Postgres URL to
  `postgresql+psycopg://` (same psycopg3 gotcha the live entrypoints handle),
  **skip** schema creation, start gunicorn.
- **One service** (review of main_ui's DB) with the Dockerfile + env vars + a
  generated domain.

## Safety (non-negotiable)

- **No writes**: only SELECTs; never `create_all`. Prefer a read-only Postgres
  role for defense-in-depth.
- **Auth gate** on every route — it exposes all students' messages and uploaded
  images, which the live apps deliberately wall off by session/email.
- Treat it as student PII (emails + conversation content); keep it off public
  discovery.

## Open items to confirm before coding

- ~~Title~~ → **decided:** `AskTIM · Database Beta`.
- ~~Colors~~ → **decided:** match main_ui (MIT crimson `#8c1a1b`).
- **Auth** — single shared password enough, or per-reviewer logins / SSO?
- **Search/filter** — beyond sort-by-date/student, want filters (course,
  exercise, date range, full-text message search)? Add now vs. later.

---

## Implementation checklist

### Phase 0 — Confirm spec
- [x] Title → `AskTIM · Database Beta`
- [x] Color → match main_ui (MIT crimson `#8c1a1b`)
- [ ] Confirm auth model (shared password vs per-user)
- [ ] Decide search/filter scope for v1

### Phase 1 — Skeleton + DB connectivity ✅
- [x] Create `database_ui/` package (`__init__`, `__main__`, `run_app` factory)
- [x] `config.py` reading `DATABASE_UI_DATABASE_URL`, `DATABASE_UI_TITLE`, `DATABASE_UI_ACCENT`, `DATABASE_UI_PASSWORD`, `DATABASE_UI_SECRET_KEY`, `PORT`
- [x] `db/models.py` — minimal read-only models (common columns only)
- [x] `db/session.py` — engine + Session, pg-url normalize, **no `create_all`** (rolls back, never commits)
- [x] `services/conversations.py` — `list_all_conversations()` (date/student sort, pagination), `get_conversation()`, `get_messages_for_conversation()`, `get_image()`
- [x] Verified end-to-end against seeded SQLite (model mapping + all services, 11/11 checks)
- [ ] Confirm against the real prod DB via `DATABASE_PUBLIC_URL` (needs the connection string — run locally)

### Phase 2 — Endpoints ✅
- [x] `GET /api/conversations` (all convos, `?sort=date|student`, pagination, `message_count`)
- [x] `GET /api/conversation/<uuid>` (full transcript, no ownership check)
- [x] `GET /api/image/<int>` (serve bytes, no ownership check)
- [x] Verified via Flask test client (14/14 checks: login flow + all APIs)

### Phase 3 — Frontend (reuse main_ui + strip) ✅
- [x] Port main_ui CSS + vendored marked/dompurify; lean new `database.js`
- [x] No chat composer / Edit context / New chat — no input affordances
- [x] Sidebar from `/api/conversations`; email line above the `Exercise · date · N msgs` line
- [x] Sort toggle: date / student (grouped by email) — verified
- [x] Anonymous fallback for null email
- [x] Transcript pane reuses message renderer (markdown + reasoning + inline images) — verified via screenshots

### Phase 4 — Title (look already matches main_ui) ✅
- [x] Inject `DATABASE_UI_TITLE` (`AskTIM · Database Beta`) into header + `<title>`
- [x] main_ui's crimson accent (`#8c1a1b`); `DATABASE_UI_ACCENT` optional override

### Phase 5 — Auth ✅
- [x] `auth.py` shared-password gate + signed session cookie
- [x] Guard all routes; `/login` + POST + `/logout` — verified

### Phase 6 — Deploy
- [x] `Dockerfile_database` (from `Dockerfile_main`) + `scripts/railway-entrypoint-database.sh` (fails closed without `DATABASE_UI_PASSWORD`)
- [ ] Deploy the review service (main_ui's DB), verify, generate domain  *(user step — needs Railway service + `DATABASE_UI_DATABASE_URL` reference var + `DATABASE_UI_PASSWORD`/`DATABASE_UI_SECRET_KEY` secrets)*
- [ ] Confirm read-only (no schema writes), auth required, title + crimson correct

### Phase 7 — Docs ✅
- [x] `database_ui/README.md` (run locally, env vars, deploy notes)
- [x] Linked from root `README.md`
