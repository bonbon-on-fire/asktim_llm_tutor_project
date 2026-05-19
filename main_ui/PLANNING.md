# main_ui — Implementation Planning

Step-by-step build plan for `main_ui/`, the production-shape embeddable tutor app.

For the overall design (problem, decisions, schema, routes, identity flow, non-goals), see [Phase 8 of the main PLANNING.md](../PLANNING.md). This file tracks **how each step gets built**, in order.

---

## Step 1: Folder skeleton + Flask app + `python -m main_ui` boots ✦ COMPLETED

**Goal:** Create the minimal package structure and a Flask app that responds to a health check. No database, no chat, no templates yet — just confirm the package is importable, the server boots on port 5001, and `python -m main_ui` works end to end.

This is the foundation every other step builds on. Keep it tiny and obviously correct.

### Files to create

```text
main_ui/
  __init__.py           # empty package marker
  __main__.py           # python -m main_ui entry point
  run_app.py            # Flask app factory + health check route
  config.py             # env-driven config dataclass
  README.md             # quick start, env vars, comparison with web_ui
  PLANNING.md           # this file
```

No subfolders yet — `db/`, `routes/`, `services/`, `templates/`, `static/`, `uploads/`, `tests/` are added in later steps.

### Purpose of each file

**`main_ui/__init__.py`**
- **Purpose:** marks `main_ui/` as a Python package so it can be imported and run as `python -m main_ui`.
- **Owns:** nothing (empty file).
- **Used by:** Python's import machinery; every other file in the package.

**`main_ui/config.py`**
- **Purpose:** central place for environment-driven settings. Reads env vars once at startup and returns a frozen, type-checked config object the rest of the app uses.
- **Owns:** the `Config` shape — currently `secret_key`, `database_url`, `port`. New settings (Postgres pool size, upload limits, CSP origins, etc.) get added here in later steps.
- **Defaults:** dev-friendly fallbacks for every value so the app boots without an `.env` file (`dev-insecure-key`, local SQLite path, port 5001).
- **Why a dataclass:** explicit fields, type hints, immutable, easy to unit-test by constructing a `Config` directly.
- **Used by:** `run_app.py` (to set Flask's `SECRET_KEY`) and `__main__.py` (to choose the port). Later steps add DB engine creation in Step 2.

**`main_ui/run_app.py`**
- **Purpose:** Flask app factory. The single function `create_app()` builds and returns a configured Flask instance. Importing `app` at module level gives gunicorn (and tests, and any other importer) a ready-to-use WSGI object.
- **Owns:** Flask app construction, route registration, and any app-level middleware/teardown wiring.
- **In Step 1:** registers exactly one route — `GET /health` returning `{"status": "ok", "service": "main_ui"}`. Later steps add blueprints from `routes/`, DB session lifecycle, error handlers, CSP headers, etc.
- **Factory-pattern rationale:** keeps testing easy (each test can `create_app()` with a different config) and avoids module-import side effects beyond the single `app = create_app()` line.

**`main_ui/__main__.py`**
- **Purpose:** entry point for `python -m main_ui`. Boots Flask's development server on the configured port with debug mode enabled.
- **Owns:** nothing the app needs at runtime — it's just glue between the CLI invocation and the Flask app.
- **Not used in production:** the production path is `gunicorn main_ui.run_app:app`. This file exists purely for local dev convenience.
- **Why a separate file:** standard Python convention — `python -m <package>` looks for `<package>/__main__.py`. Keeps the boot command tiny.

**`main_ui/README.md`**
- **Purpose:** quick-reference doc for a developer who has never touched this folder before. Covers what `main_ui/` is, how to boot it, how to verify it's running, and how it differs from `web_ui/`.
- **Owns:** local dev quick-start (`python -m main_ui`), health-check URL, supported env vars (`MAIN_UI_SECRET_KEY`, `DATABASE_URL`, `PORT`), and a short comparison with `web_ui/` (with a link to the Phase 8 comparison table in the root `PLANNING.md`).
- **Grows over time:** later steps add sections for DB migrations (Step 2), iframe testing (Step 10), running tests (Step 11), etc.

**`main_ui/PLANNING.md`** *(this file)*
- **Purpose:** the implementation roadmap for `main_ui/`. The root `PLANNING.md` says *what* Phase 8 is and *why*; this file says *how* it gets built, step by step.
- **Owns:** the ordered step list, acceptance criteria for each step, and the running record of which step is active.
- **Lives inside `main_ui/`:** keeps build planning next to the code it describes, mirroring the pattern of `meeting_notes/` and `docs/` co-located with their context.

### Dependencies

- **Flask** — already in the root `requirements.txt` (used by `web_ui/`). No new packages for Step 1.
- **Python 3.11+** (assumed; matches project baseline).

### Acceptance criteria

1. `python -m main_ui` boots and prints Flask's "Running on http://127.0.0.1:5001" banner.
2. `curl http://127.0.0.1:5001/health` returns HTTP 200 with body `{"status": "ok", "service": "main_ui"}`.
3. No port collision with `web_ui` (which uses port 5000).
4. No imports from `web_ui/`, `tutor/`, `students/`, or `judge/` yet — Step 1 stays fully self-contained.
5. `from main_ui.run_app import app` works from anywhere in the repo (for future gunicorn compatibility).
6. The Flask app uses the factory pattern (`create_app()`) so later steps can wire in DB session, blueprints, etc. without rewriting boot code.

### Verification steps

```powershell
# Boot the app
python -m main_ui

# In a second terminal, hit the health endpoint
curl http://127.0.0.1:5001/health

# Expected response:
# {"service":"main_ui","status":"ok"}

# Confirm no port conflict by also running web_ui (optional)
python -m web_ui    # binds to 5000
# Both apps should coexist
```

### What's deliberately NOT in Step 1

- No `db/` folder, no SQLAlchemy, no Postgres connection — that's Step 2
- No `/embed` route, no chat HTML, no static assets — Step 3+
- No tutor integration (`tutor.run_tutor`) — Step 4
- No `/api/chat` endpoint — Step 5
- No frontend code — Step 6
- No email modal, identity, or cookies — Step 7
- No history sidebar — Step 8
- No image uploads — Step 9
- No `test_host.html` — Step 10
- No tests — Step 11

### Risks / gotchas

- **Port mismatch**: If `PORT` env var is set to something other than 5001 (e.g. by another tool), the app picks that up. Document the override behavior in the README so it's obvious.
- **Flask debug mode**: We're keeping `debug=True` for dev convenience. Document that production hosting (when it comes) must turn this off.
- **`SECRET_KEY`**: Defaults to `"dev-insecure-key"`. Fine for local dev. Note in README that production needs a real key.

---

## Step 2: Database schema + Alembic migrations + SQLAlchemy models ✦ COMPLETED

**Verified on both SQLite and PostgreSQL 18.4** (native Windows install via winget — `PostgreSQL.PostgreSQL.16` pulled 18.4). The same migration script + env-var swap exercised both backends; tables, indexes, FK cascades, and CHECK constraint all present on both. Round-trip insert/cascade-delete and downgrade/upgrade reversibility confirmed against each.

**Implementation note:** `Message.id` and `UploadedImage.id` use `BigInteger().with_variant(Integer, "sqlite")` because SQLite only autoincrements columns typed exactly `INTEGER PRIMARY KEY`. The variant gives BIGINT on Postgres and INTEGER on SQLite, transparent to the ORM.

**Local dev workflow (verified):**
- SQLite: no env vars needed; defaults to `sqlite:///./main_ui.db`.
- Postgres: `$env:DATABASE_URL = "postgresql+psycopg://postgres:<password>@localhost:5432/tutor"` (the `tutor` database was created via `psql -U postgres -d postgres -c "CREATE DATABASE tutor"`).

**Goal:** Stand up the persistence layer. Define SQLAlchemy 2.x models for `Conversation`, `Message`, and `UploadedImage`. Wire Alembic so we can version the schema. Get `alembic upgrade head` working against both SQLite (the dev default, zero setup) and PostgreSQL (via Docker, mirrors production). No HTTP routes touch the DB yet — that's Step 3+.

This step makes the database real but doesn't connect it to the Flask app yet. Engine + session wiring into `run_app.py` happens in Step 3 when the first route actually needs to read/write.

#### Files to create

```text
main_ui/
  db/
    __init__.py                          # package marker; re-exports public API
    models.py                            # SQLAlchemy 2.x DeclarativeBase + 3 model classes
    session.py                           # engine + session factory built from config.database_url
    migrations/
      alembic.ini                        # Alembic configuration
      env.py                             # imports Base.metadata; reads DATABASE_URL at run time
      script.py.mako                     # Alembic's revision template
      versions/
        <hash>_initial_schema.py         # autogenerated first migration
```

Plus a small touch-up to the root `requirements.txt` to add the new deps.

#### Purpose of each file

**`main_ui/db/__init__.py`**
- **Purpose:** package marker and public API surface for the `db` subpackage. Re-exports `Base`, the three model classes (`Conversation`, `Message`, `UploadedImage`), and the session helpers (`engine`, `SessionLocal`, `get_session`).
- **Why a re-export hub:** callers write `from main_ui.db import Conversation` without caring about whether the class lives in `models.py` or somewhere else. Lets us split files later without breaking imports.

**`main_ui/db/models.py`**
- **Purpose:** the single source of truth for the database schema. Declares the SQLAlchemy 2.x `DeclarativeBase` and the three ORM classes that mirror the tables described in Phase 8 of the root `PLANNING.md`.
- **Owns:**
  - `Base` — declarative base shared by every model
  - `Conversation` — `id` (UUID, Python-generated), `session_id`, `email` (nullable), `course`, `exercise_number`, `tutor_prompt`, `started_at`, `last_active_at`
  - `Message` — `id` (BigInteger), `conversation_id` (FK → Conversation, cascade delete), `turn`, `role` (CHECK constraint: `'student'` or `'tutor'`), `content`, `pedagogical_reasoning` (nullable, only set for tutor rows), `created_at`
  - `UploadedImage` — `id` (BigInteger), `message_id` (FK → Message, cascade delete), `filename`, `mime_type`, `size_bytes`, `created_at`
- **Relationships:** `Conversation.messages` (one-to-many), `Message.uploaded_images` (one-to-many). Both with `cascade="all, delete-orphan"` so deleting a Conversation cleans up its messages and their images.
- **Indexes:** `email` and `session_id` on `conversations`; `conversation_id` on `messages`; `message_id` on `uploaded_images` (the last comes for free with the FK in Postgres but is explicit for SQLite).
- **Portable types:**
  - UUIDs use SQLAlchemy 2.x `Uuid(as_uuid=True)` — Postgres stores native UUID, SQLite stores TEXT, ORM exposes `uuid.UUID` either way.
  - Timestamps use `DateTime(timezone=True)` — Postgres uses TIMESTAMPTZ; SQLite has no timezone support but the ORM layer normalizes Python-side datetimes to UTC before writing.
  - UUID generation is Python-side (`default=uuid.uuid4`) so we don't depend on `gen_random_uuid()` (Postgres-only).

**`main_ui/db/session.py`**
- **Purpose:** build the SQLAlchemy engine and session factory from `config.database_url`. One place that knows how to connect to the DB.
- **Owns:**
  - `engine` — module-level singleton built lazily from `load_config().database_url`
  - `SessionLocal` — `sessionmaker` bound to the engine
  - `get_session()` — context manager that yields a session and commits/rolls-back on exit
- **Cross-driver handling:**
  - For SQLite URLs: passes `connect_args={"check_same_thread": False}` so the Flask dev server can share connections across request threads
  - For Postgres URLs (`postgresql+psycopg://...`): standard pooling, no special connect args
- **Not yet wired into Flask:** Step 3 imports `SessionLocal` from here when `/api/whoami` is added. Until then, this module is exercise-able only via Alembic and ad-hoc Python.

**`main_ui/db/migrations/alembic.ini`**
- **Purpose:** Alembic's main config file. Tells Alembic where to find `env.py`, the script template, and the `versions/` dir. Logging config also lives here.
- **Notable:** the `sqlalchemy.url` line is intentionally **empty** — `env.py` reads `DATABASE_URL` from the environment at run time instead of hardcoding it. This is what makes the same migration script work against SQLite and Postgres.
- **Invocation:** all migration commands point at this file explicitly — `alembic -c main_ui/db/migrations/alembic.ini upgrade head`.

**`main_ui/db/migrations/env.py`**
- **Purpose:** Alembic's environment script — the glue between Alembic and our SQLAlchemy models. Imports `Base.metadata` from `main_ui.db.models`, reads `DATABASE_URL` from the environment, and wires both into Alembic's context.
- **Owns:** the offline (SQL-script generation) and online (direct execution) Alembic modes. Both modes call `Base.metadata` as `target_metadata` so `alembic revision --autogenerate` can detect new/changed models.

**`main_ui/db/migrations/script.py.mako`**
- **Purpose:** Alembic's template file for new revision scripts. Used by `alembic revision`/`alembic revision --autogenerate`.
- **Owns:** nothing project-specific — usually copied verbatim from `alembic init`. We keep it untouched unless we want to customize the generated docstrings or imports.

**`main_ui/db/migrations/versions/<hash>_initial_schema.py`**
- **Purpose:** the first migration. Creates the three tables, their indexes, the FK constraints, and the CHECK constraint on `messages.role`.
- **Generated, then hand-reviewed:** we run `alembic revision --autogenerate -m "initial schema"`, then read the result top to bottom and fix anything autogen misses (autogenerate is good but not perfect — CHECK constraints and some index naming sometimes need manual touch-up).
- **Note on UUID columns:** verify the autogenerated `op.create_table(... sa.Uuid())` works on both backends. If not, drop in `sa.String(36)` with a converter at the ORM layer instead.

**Root `requirements.txt` additions**
- `sqlalchemy>=2.0` — the ORM
- `alembic` — schema migrations
- `psycopg[binary]>=3.1` — PostgreSQL driver. Used by Postgres backend; SQLite uses the stdlib `sqlite3` and needs no extra package.

#### Dependencies

- **SQLAlchemy 2.x** (uses 2.0 typed declarative style, not the legacy 1.x style)
- **Alembic** (pairs naturally with SQLAlchemy)
- **psycopg v3** (`psycopg[binary]`) — modern, async-capable Postgres driver; binary wheel avoids needing a system C compiler
- **Docker** (only when testing against Postgres locally) — `docker run --name tutor-postgres -e POSTGRES_PASSWORD=dev -e POSTGRES_DB=tutor -p 5432:5432 -d postgres:16`

#### Cross-backend portability

This is the riskiest part of Step 2 because dev (SQLite) and production (Postgres) behave differently in subtle ways.

| Concern | SQLite behavior | Postgres behavior | How we handle it |
| --- | --- | --- | --- |
| UUID primary keys | Stored as TEXT | Native UUID | `sa.Uuid(as_uuid=True)` + Python-side `default=uuid.uuid4` |
| `BIGSERIAL` / autoincrement | `INTEGER PRIMARY KEY AUTOINCREMENT` | `BIGSERIAL` | `Mapped[int] = mapped_column(BigInteger, primary_key=True)` — SQLAlchemy emits the right thing per dialect |
| `TIMESTAMPTZ` | No timezone support (stores naive datetime) | Native | `DateTime(timezone=True)` + always write tz-aware datetimes in Python |
| `gen_random_uuid()` | Doesn't exist | Native | Generate UUIDs in Python, not in the DB default |
| CHECK constraints | Supported | Supported | Same definition works for both |
| Foreign-key cascade | Must enable per-connection (`PRAGMA foreign_keys=ON`) | On by default | Set `connect_args={"check_same_thread": False}` + listen for `connect` events to enable FK enforcement on SQLite |
| Connection pooling | Not relevant (single-file DB) | Real pooling needed | Default SQLAlchemy pool is fine for both at our scale |

#### Acceptance criteria

1. `from main_ui.db import Base, Conversation, Message, UploadedImage, SessionLocal, get_session` imports cleanly from any working directory.
2. `alembic -c main_ui/db/migrations/alembic.ini upgrade head` succeeds against the default SQLite URL (`sqlite:///./main_ui.db`) and produces a file with the three tables.
3. The same command succeeds against a Dockerized Postgres (`postgresql+psycopg://postgres:dev@localhost:5432/tutor`) — `DATABASE_URL` env var is the only thing that changes.
4. After `upgrade head`, all three tables exist with the correct columns, FK constraints, CHECK constraint on `messages.role`, and the four named indexes.
5. Round-trip test passes: insert a Conversation → insert a Message linked to it → insert an UploadedImage linked to the Message → query all three back → delete the Conversation → confirm cascade removed the Message and UploadedImage rows.
6. `alembic downgrade base` cleanly drops all three tables (round-trip reversibility — useful when iterating in dev).

#### Verification steps (manual)

1. Run `pip install -r requirements.txt` after adding the new deps.
2. Apply the migration against SQLite (no setup): `alembic -c main_ui/db/migrations/alembic.ini upgrade head`. Inspect `main_ui.db` with the SQLite browser of your choice (or `sqlite3 main_ui.db ".tables"`) and confirm three tables.
3. Start a Postgres container, switch `DATABASE_URL` to point at it, re-run the same upgrade command, and confirm the same tables exist (`psql ... -c "\dt"`).
4. Run a short ad-hoc Python session that imports the models, opens a session via `get_session()`, performs the round-trip insert/query/delete described in acceptance criterion 5.

#### What's deliberately NOT in Step 2

- **Flask integration of the engine/session lifecycle** — Step 3 adds `SessionLocal()` per-request handling once a route actually uses the DB.
- **`flask-sqlalchemy`** — we use plain SQLAlchemy 2.x; the Flask integration helper would be a separate concern and is not needed yet.
- **Model methods or business logic** — models are dumb data shapes here. Conversation create/append logic lives in `main_ui/services/conversation.py` later.
- **Per-conversation last-active-timestamp updates** — wired in Step 5 when chat actually mutates conversations.
- **Tests** — Step 11.
- **Production Postgres setup** — local Docker only; managed-DB provisioning is a later phase.

#### Risks / gotchas

- **Autogenerate quirks:** Alembic's `--autogenerate` doesn't always detect CHECK constraints or some index renames. Always read the generated migration top-to-bottom before committing it.
- **SQLite FK enforcement:** SQLite ships with FK enforcement *off* by default. If we don't enable it via a `PRAGMA foreign_keys=ON` listener in `session.py`, our cascade-delete tests will silently fail.
- **UUID display:** SQLite stores UUIDs as TEXT (hyphenated strings); Postgres stores them as native UUID. The ORM layer normalizes both to `uuid.UUID`, but raw `SELECT *` output looks different between the two — don't be alarmed.
- **Timezone confusion:** Python's `datetime.utcnow()` is timezone-*naive*. We must use `datetime.now(timezone.utc)` (or equivalent) so the values written are tz-aware and Postgres-friendly.
- **Migration script must be committed:** the generated `versions/<hash>_initial_schema.py` lives in git. Future devs running `alembic upgrade head` reuse it — don't regenerate it after the first commit.
- **`DATABASE_URL` precedence:** if a `.env` file or shell var sets `DATABASE_URL` to something unexpected, both the app and Alembic use it. Make this explicit in the README so a stale env var doesn't silently send dev writes to a different DB.

---

## Step 3: Session cookie management + `/api/whoami` + `/embed` route ✦ COMPLETED

**Verified locally** via curl + cookie-jar: cookie issuance on first load (all 6 attributes — `HttpOnly`, `SameSite=None`, `Secure`, `Partitioned`, `Max-Age=15552000`, `Path=/`), no re-issuance on subsequent calls, `/api/whoami` returns the same session id across calls, and all six 404 validation paths (missing/unknown course, missing/bad-format/unknown exercise, unknown tutor) return the expected JSON error body.

**Gotcha noted during verification:** .NET `HttpClient`'s default `CookieContainer` silently drops cookies with the `Partitioned` attribute, so PowerShell-side cookie tests appeared to fail. Curl with `-c`/`-b` works correctly. Worth knowing if anyone writes a Windows-native integration test against `main_ui` — use `requests` or `curl`, not `HttpClient`.

**Goal:** First user-visible touch point. Issue an anonymous `tutor_session_id` cookie on first arrival, expose it (and the other identity placeholders) via `GET /api/whoami`, and add a `GET /embed` route that validates its `course`/`exercise`/`tutor` query parameters and serves a minimal placeholder HTML page. The actual chat UI and DB writes come later (Steps 5–6); this step lays down the routing, identity, and validation skeleton.

This step deliberately does **not** touch the database. Cookies are self-contained: the session id lives in the cookie itself; no DB row is created until the first message lands (Step 5). DB wiring into Flask is deferred to Step 4 / Step 5 when a route actually reads or writes a row.

#### Files to create

```text
main_ui/
  cookies.py                          # cookie attribute helpers + session UUID generation
  routes/
    __init__.py                       # package marker
    embed.py                          # GET /embed (Blueprint: embed_bp)
    identity.py                       # GET /api/whoami (Blueprint: identity_bp)
  templates/
    embed.html                        # minimal placeholder page (real chat UI in Step 6)
```

Plus edits to existing files:
- `main_ui/run_app.py` — register the new blueprints, install `before_request` / `after_request` hooks for session-cookie issuance
- `main_ui/config.py` — add a cookie-settings group (cookie name, max-age, optional dev-mode override for `Secure`)

#### Purpose of each file

**`main_ui/cookies.py`**
- **Purpose:** single source of truth for cookie names, default attributes, and the UUID generator that mints new session ids. Routes never construct cookie attributes inline — they go through helpers here so the policy stays consistent.
- **Owns:** `SESSION_COOKIE_NAME = "tutor_session_id"`, `EMAIL_COOKIE_NAME = "tutor_email"` (used in Step 7 but defined here now to keep the policy in one place), a `new_session_id() -> str` helper, and a `default_cookie_kwargs()` helper returning the dict passed to Flask's `response.set_cookie(...)`.
- **Default attributes:** `HttpOnly=True`, `SameSite="None"`, `Secure=True`, `Partitioned=True`, `Max-Age=15552000` (180 days). All chosen for iframe / third-party cookie context per Phase 8 of the root `PLANNING.md`.
- **Dev escape hatch:** if `config.cookie_secure_override` is `False` (toggled via env), `Secure` is omitted so cookies work on plain `http://localhost` in browsers that don't treat localhost as a secure context. Default stays `True`.

**`main_ui/routes/__init__.py`**
- **Purpose:** package marker. Empty for now. Later steps may add a `register_all(app)` helper if blueprint registration grows beyond a few imports.

**`main_ui/routes/embed.py`**
- **Purpose:** owns `GET /embed`. Reads the `course`, `exercise`, and optional `tutor` query params, validates each against the filesystem, and renders `embed.html` with the validated values passed into the template context.
- **Validation rules:**
  - `course` — must match an existing subdirectory under `curriculum/` (no path traversal allowed; exact-name comparison only).
  - `exercise` — must match an existing file `curriculum/<course>/exercise_<NN>.txt` (zero-padded two-digit number).
  - `tutor` (optional) — must match a file `tutor/prompts/<tutor>.txt`. Defaults to `tutor_05` per the Phase 8 decision.
- **Errors:** any failed validation returns HTTP `404` with a small JSON body explaining which parameter was bad. We use 404 (not 400) because from a student's perspective the resource doesn't exist; surfacing input-shape errors as 400 leaks internal detail to embedders.
- **Owns:** the `embed_bp` Blueprint, the param-validation helpers (or imports them from a shared validator module if it grows), and nothing else.

**`main_ui/routes/identity.py`**
- **Purpose:** owns `GET /api/whoami`. Reads the current request's cookies and returns `{session_id, email, conversation_id}` as JSON. In Step 3 only `session_id` is ever populated; `email` is read from the `tutor_email` cookie (set in Step 7 — will be `null` until then); `conversation_id` is always `null` until Step 5 introduces conversations.
- **Owns:** the `identity_bp` Blueprint and a thin helper that maps the request's cookies to the response shape.
- **Why a separate file:** identity-related endpoints will grow (Step 7 adds `POST /api/email`, possible future endpoints for cookie clearing / logout). Putting them together keeps the responsibility focused.

**`main_ui/templates/embed.html`**
- **Purpose:** minimal placeholder page. Renders `<title>` from the course title, embeds the validated `course`, `exercise`, and `tutor` values as JSON in a `<script type="application/json" id="tutor-config">` block so the eventual `chat.js` can read them without re-parsing the URL, and shows a brief "Tutor loading..." message in `<body>`.
- **In Step 3:** no styling beyond basic readable defaults; no JS; no chat composer. It's just a confidence-check that the route works end-to-end and the cookie gets set.
- **Owns:** the future home of the chat scaffolding (Step 6), but for now it's intentionally bare.

**`main_ui/run_app.py` (modified)**
- **Adds:**
  - Import and registration of `embed_bp` and `identity_bp`
  - `@app.before_request` hook: reads the `tutor_session_id` cookie; if absent, generates a new UUID and stores it on `flask.g.session_id` (also flags `flask.g.session_id_is_new = True`)
  - `@app.after_request` hook: if `g.session_id_is_new`, sets the cookie on the outgoing response using `default_cookie_kwargs()` from `cookies.py`
- **Why hooks rather than per-route helper:** every route in `main_ui/` will need the session id (Steps 4–9 all depend on it). Centralizing the read/issue logic means individual route handlers never have to remember the cookie dance.

**`main_ui/config.py` (modified)**
- **Adds:**
  - `cookie_secure: bool` (default `True`) — read from `MAIN_UI_COOKIE_SECURE` env var; `False` for dev when testing without HTTPS on a browser that strictly enforces `Secure`
  - `cookie_max_age_seconds: int` (default 180 × 24 × 3600 ≈ 6 months) — env override via `MAIN_UI_COOKIE_MAX_AGE`
- **Why expose these:** they're policy that may need tuning between local dev, future production deployments, and tests. Keeping them in `Config` follows the existing pattern.

#### Cookie design summary

| Attribute | Value | Why |
| --- | --- | --- |
| `Name` | `tutor_session_id` | Anonymous per-browser identifier |
| `Value` | UUIDv4 | Cryptographically random, collision-resistant |
| `HttpOnly` | `True` | JS can't read it; defends against XSS leaking the session id |
| `SameSite` | `None` | Required for the cookie to be sent when `main_ui` is loaded inside an iframe on a different origin |
| `Secure` | `True` (dev override available) | Required by browsers whenever `SameSite=None` |
| `Partitioned` | `True` | CHIPS — cookie is partitioned by top-level site, the modern story for third-party cookies in Chrome/Edge |
| `Max-Age` | ~180 days | Long enough for a semester of OCW course usage |
| `Path` | `/` | Available to every route under `main_ui` |

#### URL parameter validation

`GET /embed` accepts three query params. Validation is whitelist-based: each value must match an existing on-disk artifact, not just a regex pattern. This prevents path-traversal attacks (`course=../../etc`) and also gives a meaningful 404 when a course is misspelled.

| Param | Required | Default | Validation |
| --- | --- | --- | --- |
| `course` | yes | — | Must be a direct child of `curriculum/` (directory, not file). Exact-name match. |
| `exercise` | yes | — | Must be a two-digit number (`01`-`99`) and `curriculum/<course>/exercise_<NN>.txt` must exist. |
| `tutor` | no | `tutor_05` | Must be a stem (e.g. `tutor_05`) and `tutor/prompts/<tutor>.txt` must exist. |

#### Dependencies

No new packages. Uses only `flask` (already installed) and Python stdlib (`uuid`, `pathlib`).

#### Acceptance criteria

1. **Blueprints register.** `python -m main_ui` boots and `GET /api/whoami` and `GET /embed?course=cities_and_climate_change&exercise=04` both return non-error responses.
2. **First-load cookie issuance.** A first request without any cookies receives a response with `Set-Cookie: tutor_session_id=<uuid>; ...` containing all the policy attributes (`HttpOnly`, `SameSite=None`, `Secure`, `Partitioned`, `Max-Age=15552000`).
3. **Cookie persistence.** A subsequent request that echoes the `tutor_session_id` cookie back receives **no** new `Set-Cookie` header for that name — the existing session id is reused.
4. **`/api/whoami` shape.** Returns JSON `{session_id, email, conversation_id}`. `session_id` is a valid UUID string; `email` is `null` (no `tutor_email` cookie set yet); `conversation_id` is `null`.
5. **`/embed` happy path.** A request with valid `course` and `exercise` (e.g. `cities_and_climate_change` + `04`) returns 200 with HTML whose `<script id="tutor-config">` contains the validated values.
6. **`/embed` validation failures.** Each of these returns 404 with a JSON body naming the bad param: missing `course`, unknown `course`, missing `exercise`, unknown `exercise` for the course, unknown `tutor`.
7. **`tutor` default.** A request that omits `tutor` is accepted; the rendered config shows `tutor_05`.
8. **`/health` still works.** The Step 1 endpoint continues to respond with `{"status": "ok", "service": "main_ui"}`.

#### Verification steps (manual)

1. `python -m main_ui` to boot.
2. Curl the embed happy path: `curl -i http://127.0.0.1:5001/embed?course=cities_and_climate_change&exercise=04`. Confirm 200, HTML body, `Set-Cookie` header on first call.
3. Re-curl with the cookie echoed back: `curl -i --cookie "tutor_session_id=<uuid>" http://127.0.0.1:5001/embed?course=cities_and_climate_change&exercise=04`. Confirm 200 and **no** new `Set-Cookie` for `tutor_session_id`.
4. Hit `/api/whoami` with the cookie: confirm JSON shape.
5. Hit each of the 404 cases (bad course, bad exercise, bad tutor) and confirm the JSON error body names the offending param.
6. Open `http://127.0.0.1:5001/embed?course=cities_and_climate_change&exercise=04` in a real browser; open DevTools → Application → Cookies; confirm `tutor_session_id` is present with all the expected attributes.

#### What's deliberately NOT in Step 3

- **No database access** — no Conversation row created on `/embed` load. The first DB write happens when the student sends a message (Step 5).
- **No Flask ↔ SQLAlchemy session lifecycle** — `before_request` / `after_request` only manage the cookie. Step 4 or Step 5 will add per-request DB session handling when the first DB-touching route appears.
- **No real chat UI in `embed.html`** — only a "Tutor loading…" placeholder and the embedded config block. Real markup + composer in Step 6.
- **No email handling** — `EMAIL_COOKIE_NAME` is defined in `cookies.py` so Step 7 can use it, but the cookie is never read or written in Step 3.
- **No `/api/chat`** — Step 5.
- **No history sidebar / `/api/history`** — Step 8.
- **No tests** — Step 11.

#### Risks / gotchas

- **`Secure` on `http://localhost`:** Chrome treats localhost as a secure origin so `Secure` cookies work there. Firefox and Safari are stricter and may refuse to set them on plain HTTP. Mitigation: the `MAIN_UI_COOKIE_SECURE=false` override exists for cross-browser dev. Document this in the README and only flip it when actually debugging on a stricter browser.
- **`Partitioned` attribute compatibility:** the CHIPS attribute is Chrome 118+, Edge 118+, recent Firefox. Older browsers ignore unknown attributes harmlessly. No behavior change needed; just be aware that pre-118 Chrome will treat the cookie as a regular third-party cookie (potentially blocked by 3rd-party-cookie phase-out).
- **Path-traversal in `course`:** never `os.path.join` a user-supplied value with a base path without confirming the resulting path is still inside the base. The plan calls for exact-name matching against `os.listdir("curriculum/")` results, which sidesteps the issue.
- **`tutor` default drift:** hard-coding `tutor_05` as the default works today but will rot when `tutor_06` ships. Acceptable trade-off for Step 3; the alternative (scanning `tutor/prompts/` and picking max version) is a small follow-up that doesn't have to land now. Note it as a future cleanup.
- **Validation cost on every request:** `os.listdir("curriculum/")` runs on each `/embed` hit. At ~100-student traffic this is negligible. If traffic grows, cache the result with a TTL (or invalidate on file watcher events).
- **JSON injection into `<script id="tutor-config">`:** when embedding params into the HTML, use Jinja's `tojson` filter (auto-escapes for safe inclusion inside `<script type="application/json">`). Never concatenate user-supplied strings into the script block directly.

---

## Step 4: Tutor bridge ✦ COMPLETED

**Verified locally** with real OpenAI API call: single-turn smoke test (`history=[]` + new message) returned a Socratic reply referencing the actual exercise_04 content; multi-turn smoke test (history with 2 prior turns + "Boston" as the new student message) produced a coherent next-turn reply that acknowledged the chosen city and asked a more focused follow-up. Graph cache verified by checking object identity across repeat calls with the same `(tutor, course, exercise)` key.

**Implementation notes:**
- Reused upstream `tutor.run_tutor` API (`load_system_prompt`, `create_tutor_graph`, `parse_tutor_response`, and upstream `get_tutor_reply` imported under an aliased name to avoid colliding with our own).
- `build_assignment_text` reads `course.txt` (required-ish — falls through silently if absent), `syllabus.txt` (optional), and `exercise_<NN>.txt` (required). No `Run configuration` block since `main_ui` chats are open-ended.
- `.env` loading added to `main_ui/__init__.py` so `OPENAI_API_KEY` from the repo's `.env` is picked up automatically by every entrypoint without manual `$env:` setup.

**Goal:** Make `main_ui/` able to obtain a real tutor reply programmatically, by wrapping the existing `tutor.run_tutor` API in a thin bridge. No HTTP routes, no DB writes, no frontend changes — just confirm the wiring works end-to-end: feed in `(course, exercise, tutor, history, new_message)` from a Python REPL, get a tutor reply back, and we're confident Step 5 can plug it into `/api/chat`.

This step is the smallest possible "the LLM actually replies" milestone. It lets us catch wiring problems (missing env vars, import paths, message shape mismatches) before adding the complexity of conversation persistence in Step 5.

#### Files to create

```text
main_ui/
  services/
    __init__.py                       # package marker
    tutor_bridge.py                   # assignment-text builder + tutor-reply entry point
```

Plus a small edit to `main_ui/__init__.py` to auto-load `.env` at import time (so `OPENAI_API_KEY` from the project's `.env` file is available to every entrypoint without manual `$env:OPENAI_API_KEY` setup). Uses `python-dotenv` (already in `requirements.txt`). Other project modules (`tutor/`, `web_ui/`, `judge/`) deliberately don't load `.env` per Phase 2/5 cleanups — `main_ui/` reintroduces it at the package level, scoped only to this app.

#### Purpose of each file

**`main_ui/__init__.py` (modified)**
- **Adds:** a `dotenv.load_dotenv()` call at import time, pointing at the repo-root `.env`. Wrapped in a try/except for the case where `python-dotenv` is missing or the file doesn't exist — the app should still boot, just without auto-loaded env vars.
- **Why scoped to `main_ui/`:** other modules (`tutor`, `judge`, `students`, `web_ui`) deliberately don't load `.env` per the Phase 2/5 cleanups. We're not undoing that decision — we're carving a localized exception so `main_ui/` entrypoints (`python -m main_ui` and `python -c "from main_ui..."` smoke tests) don't require manual env setup.

**`main_ui/services/__init__.py`**
- **Purpose:** package marker. Empty file. Later steps may add a stable public API surface here once we have multiple services (`conversation.py`, `image_storage.py`).

**`main_ui/services/tutor_bridge.py`**
- **Purpose:** the one place in `main_ui/` that knows how to talk to `tutor.run_tutor`. Anything that needs a tutor reply (Step 5's `/api/chat`, future test scripts) calls this module — never the underlying `tutor.run_tutor` API directly.
- **Owns:**
  - `build_assignment_text(course, exercise) -> str` — concatenates `curriculum/<course>/course.txt`, optional `curriculum/<course>/syllabus.txt`, and `curriculum/<course>/exercise_<NN>.txt` into the assignment string the tutor's `<Assignment>` slot expects. Mirrors what `ui/run_ui_raw.py:_build_assignment_text` does but without the `turn_size` line (open-ended chat, no planned conversation length).
  - A module-level graph cache keyed by `(tutor, course, exercise)` so repeat calls don't rebuild the LangGraph.
  - `get_tutor_reply(*, course, exercise, tutor, history, new_student_message) -> dict` — the single public entry point.
  - Internal helpers for converting our simple message dicts (`{"role": "student"|"tutor", "content": str}`) to LangChain `HumanMessage` / `AIMessage` instances.
- **What it deliberately does NOT own:**
  - Conversation creation / DB writes — Step 5's `services/conversation.py`.
  - Cookie handling — Step 3's `cookies.py`.
  - Multimodal figure attachments — Phase 6 + Step 9.
  - Streaming — out of scope for the entire project until further notice.

#### API surface

```python
def build_assignment_text(course: str, exercise: str) -> str:
    """Build the assignment string for the tutor's <Assignment> slot."""

def get_tutor_reply(
    *,
    course: str,
    exercise: str,
    tutor: str,
    history: list[dict],          # each: {"role": "student"|"tutor", "content": str}
    new_student_message: str,
) -> dict:                         # {"reply": str, "reasoning": str | None}
    """Get one tutor reply given the conversation state and new student message."""
```

Keyword-only args on `get_tutor_reply` — there are 5 of them and they're easy to mix up positionally. The message-dict shape (`role`, `content`) matches the DB column names from Step 2 so Step 5 can pass query results in directly without remapping.

Return is a plain dict, not a dataclass — small surface, easy to JSON-serialize for Step 5's `/api/chat` response. Two keys:
- `reply` — the student-facing answer text the tutor produced
- `reasoning` — the tutor's internal `pedagogical-reasoning` (the JSON field that gets hidden from students; stored in DB for debugging and judge grading later)

#### Caching strategy

A module-level `dict[(tutor, course, exercise), CompiledStateGraph]` stores constructed graphs. Misses build via `load_system_prompt(tutor, assignment_override=build_assignment_text(...))` followed by `create_tutor_graph(system_prompt)`.

Cache lifetime = process lifetime. Restarting the Flask app drops the cache (acceptable for local dev). If curriculum files change mid-process, the cached graph stays stale until restart — surfaced as a known gotcha rather than a bug to fix now.

Not thread-safe (plain dict). Flask's dev server is single-threaded so this is fine; future production hosting with gunicorn workers needs a per-process cache anyway (same dict shape works because each worker is its own Python process).

#### Dependencies

- No new pip packages.
- Imports from existing project modules: `tutor.run_tutor` (`load_system_prompt`, `create_tutor_graph`, `get_tutor_reply` — the last one re-exported under a different local name to avoid colliding with our own function).
- Imports `HumanMessage` and `AIMessage` from `langchain_core.messages` (already a project dep).
- Requires `OPENAI_API_KEY` to be set — the existing tutor module fails fast if it isn't. The bridge inherits that behavior; no extra check needed.

#### Acceptance criteria

1. **Public API imports cleanly.** `from main_ui.services.tutor_bridge import get_tutor_reply, build_assignment_text` works from anywhere in the repo.
2. **Assignment text builds non-empty.** `build_assignment_text("cities_and_climate_change", "04")` returns a string containing both the course-level context (from `course.txt`) and the exercise text (from `exercise_04.txt`).
3. **First call succeeds.** `get_tutor_reply(course="cities_and_climate_change", exercise="04", tutor="tutor_05", history=[], new_student_message="I'm starting exercise 4. What should I do first?")` returns a dict with non-empty `reply`. The `reasoning` field is either a non-empty string or `None` (depending on whether the tutor's JSON parsed both fields).
4. **Reply respects tutor persona.** The reply is Socratic — asks a guiding question, does not deliver a direct answer. Qualitative check during smoke testing, not an assertion.
5. **Multi-turn coherence.** Calling again with a non-empty `history` list produces a continuing reply that references prior turns appropriately.
6. **Graph is cached.** A second call with the same `(tutor, course, exercise)` re-uses the cached graph. Verifiable by adding a temporary print or by inspecting the cache dict directly during testing.
7. **Existing routes unaffected.** `python -m main_ui` boots; `/health`, `/embed`, `/api/whoami` continue to respond per their Step 1-3 contracts.

#### Verification steps (manual)

```powershell
# 1. Ensure OPENAI_API_KEY is set
$env:OPENAI_API_KEY = "sk-..."

# 2. Smoke test from the repo root
python -c "from main_ui.services.tutor_bridge import build_assignment_text; print(build_assignment_text('cities_and_climate_change', '04')[:400])"

# 3. End-to-end tutor reply
python -c "from main_ui.services.tutor_bridge import get_tutor_reply; r = get_tutor_reply(course='cities_and_climate_change', exercise='04', tutor='tutor_05', history=[], new_student_message='I am starting exercise 4. Where do I begin?'); import json; print(json.dumps(r, indent=2))"

# 4. Multi-turn sanity check
python -c "from main_ui.services.tutor_bridge import get_tutor_reply; hist = [{'role':'student','content':'Hello'},{'role':'tutor','content':'Hi! What city are you studying?'}]; r = get_tutor_reply(course='cities_and_climate_change', exercise='04', tutor='tutor_05', history=hist, new_student_message='Boston.'); print(r['reply'])"

# 5. Confirm Flask still works
python -m main_ui
# In another shell:
curl http://127.0.0.1:5001/health
curl http://127.0.0.1:5001/embed?course=cities_and_climate_change&exercise=04 | head -20
```

#### What's deliberately NOT in Step 4

- **No HTTP routes** — `/api/chat` is Step 5.
- **No DB writes** — `conversations` and `messages` tables remain empty.
- **No Flask integration of session lifecycle** — the bridge is plain Python; Flask wiring happens when Step 5 adds the chat route.
- **No frontend changes** — `embed.html` placeholder stays untouched.
- **No streaming** — single request/response per call.
- **No multimodal / figures** — Phase 6 and Step 9 layer those in later.
- **No tests** — Step 11.

#### Risks / gotchas

- **`OPENAI_API_KEY` must be set or the import-time/call-time chain fails.** The existing tutor module fails fast on missing key; the bridge surfaces that error cleanly. Document in the docstring; remind during verification.
- **Cost per smoke-test call.** Every test call is a real LLM call (cents at most, but worth flagging — repeated automated runs add up). No mocking in this step; mocks belong to Step 11 tests.
- **JSON parsing fragility.** The tutor returns a JSON object with `pedagogical-reasoning` and `Student-facing-answer`. `parse_tutor_response` in `tutor.run_tutor` already handles minor malformations. The bridge does NOT add additional repair logic — if the underlying tutor returns garbage, the bridge raises whatever exception the tutor surfaces.
- **Cache staleness on curriculum edits.** Mid-process changes to `curriculum/<course>/exercise_<NN>.txt` won't reach a cached graph. Restart the process to pick up edits, or extend the cache with file-mtime tracking later if it becomes painful.
- **Path resolution for `_REPO_ROOT`.** `main_ui/services/tutor_bridge.py` is three levels deep from the repo root; use `Path(__file__).resolve().parents[2]` (same trick `routes/embed.py` uses).
- **Local name collision with `get_tutor_reply`.** Both `tutor.run_tutor` and our bridge expose a function named `get_tutor_reply`. Import the upstream one as `from tutor.run_tutor import get_tutor_reply as get_tutor_reply_upstream` to avoid shadowing.
- **Concurrency.** Module-level cache dict is not thread-safe. Flask dev server is single-threaded so this is a non-issue. Document and revisit when we hit a multi-process / multi-thread environment.

---

## Step 5: `/api/chat` text-only ✦ COMPLETED

**Verified locally** with real OpenAI API calls against a clean SQLite DB. All 10 acceptance criteria pass:
- First message creates a new conversation (`student_message_count: 1`); DB row created with correct course/exercise/tutor; student + tutor messages persisted with turn=1
- Subsequent message with the same `conversation_id` appends to the same conversation (`student_message_count: 2`, both new messages at turn=2)
- Omitting `conversation_id` while reusing the same session cookie creates a new conversation (different UUID, same session_id on the DB row)
- `last_active_at > started_at` after every exchange
- `pedagogical_reasoning` persisted in tutor `Message` rows; response payload only contains `{conversation_id, reply, student_message_count}` — no reasoning leaked
- Empty `text` → 400; invalid course/exercise/tutor → 404; malformed `conversation_id` → 400; cross-session `conversation_id` → 403
- `/health`, `/embed`, `/api/whoami` all still respond per their Step 1-3 contracts

**Refactor done in passing:** validation helpers extracted from `routes/embed.py` into `routes/_validation.py` so `/embed` and `/api/chat` share the same `validate_course` / `validate_exercise` / `validate_tutor` functions. `embed.py` is now noticeably shorter.

**Goal:** The first step that students could plausibly use (modulo a real frontend in Step 6). Add `POST /api/chat` — text-only — that:
- Resolves to a `Conversation` row (creating one on first message, reusing it via `conversation_id` thereafter)
- Persists the student's message
- Calls `tutor_bridge.get_tutor_reply(...)` to get a reply
- Persists the tutor's reply (with its hidden pedagogical reasoning) in a second row
- Updates the conversation's `last_active_at`
- Returns `{conversation_id, reply, student_message_count}` as JSON

This step is the first time everything connects: Step 2's models, Step 3's session cookie + identity, Step 4's tutor bridge, all composed inside an HTTP handler.

#### Files to create

```text
main_ui/
  routes/
    chat.py                            # POST /api/chat (Blueprint: chat_bp)
  services/
    conversation.py                    # find / create / append-to a conversation
```

Plus edits to existing files:
- `main_ui/run_app.py` — register `chat_bp`; install per-request DB session lifecycle (the wiring Step 3 deferred)

#### Purpose of each file

**`main_ui/services/conversation.py`**
- **Purpose:** the one place that knows how to put conversation rows + messages into the database. Route handlers never write to the DB directly — they call helpers here.
- **Owns:**
  - `find_or_create_conversation(db, *, session_id, conversation_id, course, exercise_number, tutor_prompt, email=None) -> Conversation` — resolves to an existing row (validating ownership by `session_id`) or inserts a new one
  - `append_exchange(db, *, conversation, student_text, tutor_text, pedagogical_reasoning) -> tuple[Message, Message]` — inserts the student/tutor pair sharing one turn number; bumps `last_active_at`
  - `get_history_for_tutor(db, conversation) -> list[dict]` — returns chronologically ordered `[{role, content}, ...]` dicts in the exact shape `tutor_bridge.get_tutor_reply` expects (zero remapping at the call site)
  - `count_student_messages(db, conversation) -> int` — count used by Step 7's email modal trigger
- **What it deliberately doesn't own:**
  - LLM calls — `tutor_bridge`
  - Cookies / session ids — `cookies.py` + route's `before_request`
  - Validation of `course`/`exercise`/`tutor` — that lives in route handlers (reused from Step 3's pattern)
  - Image storage — Step 9's `image_storage.py`

**`main_ui/routes/chat.py`**
- **Purpose:** owns `POST /api/chat`. Glues request-shape validation, the conversation service, and the tutor bridge together. Single endpoint; small body.
- **Request shape (JSON):**
  - `text` (required, string, non-empty) — the new student message
  - `course` (required, string) — must validate against `curriculum/<course>/` directory
  - `exercise` (required, string) — must validate against `curriculum/<course>/exercise_<NN>.txt`
  - `tutor` (optional, string; defaults to `tutor_05`) — must validate against `tutor/prompts/<tutor>.txt`
  - `conversation_id` (optional, UUID string) — absent on the first message of an iframe load; present on subsequent messages
- **Response shape (JSON, 200):**
  - `conversation_id` (string UUID) — caller stores this and includes it in subsequent posts
  - `reply` (string) — the student-facing answer
  - `student_message_count` (int) — number of student-role messages in this conversation after the just-inserted one; used by Step 7's "ask for email after the 3rd message" trigger
- **Error responses:**
  - `400` — missing or empty `text`
  - `404` — invalid `course`, `exercise`, or `tutor` (same validation as `/embed`)
  - `403` — `conversation_id` provided but doesn't belong to the current `session_id`
  - `502` — tutor call failed (LLM error, malformed JSON the upstream couldn't recover from, etc.)

**`main_ui/run_app.py` (modified)**
- **Adds:**
  - `from main_ui.routes.chat import chat_bp` + `app.register_blueprint(chat_bp)`
  - `@app.before_request` hook that opens a SQLAlchemy session and stashes it on `g.db` (in addition to the cookie work Step 3 added)
  - `@app.teardown_request` hook that commits on success, rolls back on exception, and always closes the session
- **Why now (and not Step 3):** Step 3's routes (`/embed`, `/api/whoami`, `/health`) don't touch the DB. Adding the session lifecycle there would have been dead code. Step 5 is where the first DB-touching route lands, so the wiring goes here.

#### Why pedagogical reasoning is persisted but NOT returned

The tutor's `pedagogical-reasoning` JSON field is intentionally hidden from students (per the project's pedagogy: students see the Socratic question, not the meta-narration about why it's Socratic). The route:
- **Persists** it on the tutor `Message` row (`pedagogical_reasoning` column) — useful for judge grading later and for admin debugging
- **Does NOT** include it in the `/api/chat` response payload — anyone with browser DevTools could see it otherwise, defeating the design intent

If a debug mode is wanted later, add a separate admin-gated endpoint or a `?debug=true` query param explicitly checked against a secret. Not part of Step 5.

#### Turn numbering

A `turn` integer column lives on `Message`. The student and tutor messages of the same exchange share the same turn number, starting at 1. `append_exchange` computes the next turn as `max(existing_turns) + 1`, or 1 if the conversation has no messages yet. This keeps the DB self-explanatory when read by hand (turn 1 = first exchange).

#### Conversation ownership / cross-session guard

If a client sends a `conversation_id` that exists in the DB but its `session_id` doesn't match the request's `g.session_id`, return `403 Forbidden`. This is a small safety net against accidentally smuggling someone else's conversation_id (e.g., a copied-and-pasted iframe URL with a stale localStorage value). The response body names the issue without leaking whether the conversation exists.

If `conversation_id` is **absent**, the route silently creates a new conversation — that's the expected fresh-iframe-load path.

#### Email pass-through (forward-compat with Step 7)

When the route creates a new conversation, it reads the `tutor_email` cookie (set in Step 7) and writes it onto the Conversation row's `email` field. For Step 5 this cookie is never set (Step 7 isn't built yet), so the field stays `NULL` — but the wiring is in place so when Step 7 lands, returning students with the email cookie automatically get their conversations linked from message #1 instead of waiting for the backfill in Step 7.

#### Dependencies

- No new pip packages.
- All imports are project-internal: `main_ui.db`, `main_ui.cookies`, `main_ui.services.tutor_bridge`, `main_ui.routes.embed` (re-uses its validation helpers — extract them to a shared module if duplication is awkward).
- Same `OPENAI_API_KEY` requirement as Step 4.

#### Acceptance criteria

1. **First message creates a conversation.** `POST /api/chat` with `{text, course, exercise, tutor}` (no `conversation_id`) returns 200 with `{conversation_id, reply, student_message_count: 1}`. DB has one `conversations` row plus two `messages` rows (student + tutor, both turn=1).
2. **Subsequent message reuses the conversation.** A second `POST /api/chat` with the returned `conversation_id` appends to the same row. After the call: 4 message rows total, two with turn=1 and two with turn=2. `student_message_count` returns `2`.
3. **Omitting `conversation_id` after one exists creates a new conversation.** Simulating a fresh iframe load (no `conversation_id` in the body) inserts a new `conversations` row, distinct from the prior one.
4. **`last_active_at` updates.** On each `POST /api/chat`, the conversation's `last_active_at` advances.
5. **`pedagogical_reasoning` persisted but not returned.** The tutor `Message` row has a non-empty `pedagogical_reasoning` column. The JSON response does NOT contain a `reasoning` or `pedagogical_reasoning` key.
6. **Empty text → 400.** `{"text": ""}` returns 400 with a JSON error body.
7. **Bad course/exercise/tutor → 404.** Validation identical to `/embed`. Response body names the offending param.
8. **Wrong-session `conversation_id` → 403.** Crafting a request that sends a real `conversation_id` from a different session returns 403.
9. **`student_message_count` is monotonic per conversation.** Subsequent messages on the same conversation increment the count by 1 each time.
10. **Steps 1-4 still work.** `/health`, `/embed`, `/api/whoami`, plus `tutor_bridge.get_tutor_reply` direct-call all behave as before.

#### Verification steps (manual)

```powershell
# Boot main_ui in another terminal: python -m main_ui

# 1. First message — no conversation_id
$body = '{"text":"I am starting exercise 4. Where do I begin?","course":"cities_and_climate_change","exercise":"04","tutor":"tutor_05"}'
$r = curl -s -c jar.txt -X POST -H "Content-Type: application/json" -d $body http://127.0.0.1:5001/api/chat
$r  # capture conversation_id from the JSON

# 2. Second message — same conversation_id
$body2 = '{"text":"Boston.","course":"cities_and_climate_change","exercise":"04","tutor":"tutor_05","conversation_id":"<paste-uuid>"}'
curl -s -b jar.txt -X POST -H "Content-Type: application/json" -d $body2 http://127.0.0.1:5001/api/chat

# 3. Inspect the DB
python -c "from main_ui.db import get_session, Conversation, Message; \
with get_session() as s: \
    convos = s.query(Conversation).all(); \
    print(f'{len(convos)} conversations'); \
    for c in convos: print(f'  {c.id} {c.course}/{c.exercise_number} email={c.email}'); \
    msgs = s.query(Message).order_by(Message.id).all(); \
    print(f'{len(msgs)} messages'); \
    [print(f'  turn={m.turn} role={m.role} content={m.content[:60]!r}') for m in msgs]"

# 4. Error cases
curl -s -X POST -H "Content-Type: application/json" -d '{"text":"","course":"cities_and_climate_change","exercise":"04"}' http://127.0.0.1:5001/api/chat  # → 400
curl -s -X POST -H "Content-Type: application/json" -d '{"text":"x","course":"nope","exercise":"04"}' http://127.0.0.1:5001/api/chat                       # → 404
curl -s -X POST -H "Content-Type: application/json" -d '{"text":"x","course":"cities_and_climate_change","exercise":"04","tutor":"tutor_99"}' http://127.0.0.1:5001/api/chat  # → 404
```

#### What's deliberately NOT in Step 5

- **No frontend** — `embed.html` placeholder remains. Real chat UI is Step 6.
- **No image uploads** — `multipart/form-data` is Step 9. Step 5's content-type is `application/json`.
- **No email flow** — `student_message_count` is returned but the modal trigger lives in the frontend (Step 7). The `/api/email` endpoint also lands in Step 7.
- **No history endpoint** — Step 8 adds `GET /api/history` and `GET /api/conversation/<id>`.
- **No streaming** — single request, single response per turn.
- **No rate limiting / abuse protection** — explicit non-goal of Phase 8.
- **No tests** — Step 11.
- **No multimodal (figures)** — Phase 6 + Step 9.

#### Risks / gotchas

- **DB session held during LLM call.** The tutor API takes 2-10 seconds. The per-request DB session stays open for that whole window. Acceptable for SQLite and small Postgres pool sizes; if we hit pool exhaustion in production, refactor to close the session before the LLM call and reopen after. Defer for now.
- **LLM cost per request.** Every successful `/api/chat` is a paid LLM call. No automated test should hit this without mocking (Step 11 will mock). Manual smoke tests cost pennies.
- **`parse_tutor_response` returning `None` for reasoning.** If the upstream tutor's JSON output is malformed enough that even `parse_tutor_response`'s three fallback strategies fail, `pedagogical_reasoning` ends up `None`. That's persisted as NULL in the DB, which is fine; just be aware when grading later.
- **Empty tutor reply.** Same root cause as above. The route should treat `reply == ""` as an error condition and return 502 rather than persisting an empty student-facing message. Defensive but cheap.
- **Concurrent writes to the same conversation.** Two `POST /api/chat` requests racing on the same `conversation_id` could produce two messages with the same `turn` number. Flask's dev server serializes requests, so this can't happen there; production hosting with worker concurrency needs either a row-level lock during turn computation or accepting the race (turns aren't a primary key, so duplicates are technically allowed). Note in the planning doc, defer the fix.
- **Validation duplication with `/embed`.** Both `/embed` and `/api/chat` validate the same three params. For Step 5 we either re-import the helpers from `routes/embed.py` (couples the modules) or copy the logic (DRY-violation). Pragmatic call: extract the validators into a small `main_ui/routes/_validation.py` module shared by both. Note the refactor in the file's docstring.
- **`conversation_id` parse error.** A client sending an invalid UUID string should get 400, not 500. Wrap `UUID(...)` in try/except.
- **Connection pool sizing.** If Postgres is used, the default pool (5 + 10 overflow) is enough for development but worth tuning before any production-style load test.

---

## Step 6: Frontend chat UI ✦ COMPLETED

**Verified locally** by opening `/embed?course=cities_and_climate_change&exercise=01` in a real browser. Working: composer enables on text, Send issues POST `/api/chat`, student bubble + tutor bubble render with whitespace preserved, `conversation_id` captured and reused on subsequent posts, `tutor_session_id` cookie set with all 6 expected attributes (visible in DevTools → Storage → Cookies → `127.0.0.1:5001`), `student_message_count` returned in each response (visible in DevTools → Network → POST `chat` → Response tab).

**Goal:** Replace the Step 3 placeholder ("Tutor loading…") with a functional chat interface — message list, composer, send button, loading indicator. The page reads `tutor-config` from its embedded JSON block, sends `POST /api/chat` over fetch, and renders replies. After this step, a student can actually have a tutoring session by opening `/embed?course=…&exercise=…` and typing.

Vanilla JS only. No framework, no build step. Matches the rest of the codebase (`web_ui/templates/index.html` is also vanilla). Step 6 is the first step that produces a visibly student-usable thing.

#### Files to create

```text
main_ui/
  static/
    js/
      chat.js                           # all chat behavior
    css/
      chat.css                          # all styling
```

Plus edits to:
- `main_ui/templates/embed.html` — replace the placeholder body with real chat scaffolding; link the new JS + CSS

No new Python — Step 5's `/api/chat` is the API surface, unchanged.

#### Purpose of each file

**`main_ui/templates/embed.html` (modified)**
- **Owns:** the HTML scaffolding — `<head>` with viewport + title + CSS link; `<body>` with three regions (message list, composer, error banner); the `<script type="application/json" id="tutor-config">` block (kept from Step 3); a `<script src="…/chat.js" defer>` link.
- **Stays declarative:** no inline JS. All behavior in `chat.js`.
- **Templated values:** the Jinja-rendered `tutor_config` dict tells JS what course/exercise/tutor this iframe is for. No other server-side rendering — every message is added by JS as the conversation progresses.

**`main_ui/static/js/chat.js`**
- **Owns:** all client-side state and behavior. One file, no modules, no bundler — loaded via a plain `<script defer>` tag.
- **Responsibilities:**
  - Read `tutor-config` JSON on load and stash it in a module-scoped object.
  - Hold conversation state: `conversation_id` (null until first POST returns one), `is_sending` (bool gate), `student_message_count` (for future Step 7 trigger).
  - Wire up DOM event handlers: send button click, Enter key (without Shift), Shift+Enter for newline, textarea auto-grow (optional, low-priority).
  - Implement `sendMessage(text)` — POST to `/api/chat`, on success render the tutor reply; on error render an inline error banner without dropping the user's typed text.
  - Implement `renderMessage({role, content})` — append a message bubble to the list with correct CSS class.
  - Implement `setSending(bool)` — toggle the composer's disabled state and the "tutor is thinking…" indicator.
  - Auto-scroll the message list to the bottom on every new message.
  - Auto-focus the textarea on page load (so embedded iframes are immediately typable).
- **What it deliberately doesn't own:**
  - No image upload UI (Step 9).
  - No email modal (Step 7).
  - No history sidebar (Step 8).
  - No streaming — single request/response per turn.
  - No markdown parsing — `white-space: pre-wrap` CSS handles `\n` line breaks; bold/italics/lists stay as raw text. Acceptable for Step 6; revisit if tutor replies start producing markdown the students miss.

**`main_ui/static/css/chat.css`**
- **Owns:** layout (flex column: list grows, composer pinned at bottom), message bubble styles (student right-aligned with one color, tutor left-aligned with another), composer styling (textarea + button), loading indicator, error banner, narrow-width responsiveness.
- **Plain CSS** — no preprocessor, no framework. One file, ~150 lines max.

#### UI layout (described in prose)

```
+-------------------------------------------+
|  [optional thin header showing the course |
|   and exercise; e.g. "cities · ex 04"]    |
+-------------------------------------------+
|                                           |
|        [tutor reply bubble, left]         |
|                                           |
|        [student message bubble, right]    |
|                                           |
|        [tutor reply bubble, left]         |
|                                           |
|        … scrollable …                     |
|                                           |
+-------------------------------------------+
| [inline error banner, only if error]      |
+-------------------------------------------+
|  +-------------------------------------+  |
|  | textarea (multiline, auto-resize)   |  |
|  +-------------------------------------+  |
|  [Send]   [tutor is thinking… indicator]  |
+-------------------------------------------+
```

- **Message bubbles:** rounded, padded; student bubbles right-aligned with a tinted background; tutor bubbles left-aligned with a neutral background. White-space: pre-wrap so the tutor's multi-line numbered lists render legibly.
- **Composer:** textarea grows up to ~6 lines then scrolls internally; Send button to the right (disabled when textarea is empty or `is_sending` is true).
- **Loading indicator:** small "tutor is thinking…" text or three-dot animation next to the Send button while a POST is in flight. No fancy spinner.
- **Error banner:** above the composer, dismissible (× button), red-ish background, plain text reason from the server's response body when available.
- **Narrow widths:** Phase 8 says iframes may live in OCW sidebars; test at 320-360px width. Composer must stay usable; message bubbles get narrower but don't break.

#### State machine

Three states, transitions are obvious:
- `idle` — composer enabled, no in-flight request
- `sending` — composer disabled, loading indicator visible, fetch in flight
- `errored` — same as `idle` but with an error banner present; banner clears on next successful send

State transitions:
- `idle` → `sending`: user submits a non-empty message
- `sending` → `idle`: response received and parsed successfully (whether HTTP 2xx or a clean error)
- Any → `errored`: HTTP error or network failure; user's typed text preserved in textarea

#### Acceptance criteria

1. **`/embed?course=cities_and_climate_change&exercise=04` renders the chat UI**, not the Step 3 placeholder text.
2. **Composer visible:** textarea + Send button render side-by-side (or stacked at narrow widths).
3. **Send works end-to-end:** typing text and clicking Send issues `POST /api/chat` with `{text, course, exercise, tutor, conversation_id?}`; on 200, the student's text appears as a bubble, then the tutor's reply appears as a separate bubble.
4. **`conversation_id` captured and reused:** after the first POST returns it, all subsequent POSTs from the same page load include it.
5. **Loading state:** while a POST is in flight, the Send button is disabled and a "tutor is thinking…" indicator is shown.
6. **Enter / Shift+Enter:** Enter sends (when text is non-empty); Shift+Enter inserts a newline.
7. **Empty text doesn't submit:** clicking Send (or pressing Enter) on an empty/whitespace-only textarea does nothing.
8. **Errors render inline:** an HTTP 4xx/5xx (e.g. tutor failure) shows the response's `reason` in an error banner; the user's typed text stays in the textarea so they can retry.
9. **Auto-scroll:** message list scrolls to bottom on each new message.
10. **Auto-focus:** textarea has focus on initial page load (so students inside an iframe can start typing immediately).
11. **Multi-turn works:** sending 5+ messages produces a coherent conversation with correct turn ordering and bubble styling.
12. **Narrow-width readable:** at 320px the layout doesn't break; bubbles fit; composer remains usable.
13. **Newlines render:** tutor replies with `\n` and numbered lists display as multi-line, not as one wall of text.
14. **No XSS:** student types `<script>alert(1)</script>` — text renders literally, no script execution.
15. **All Step 1-5 endpoints still respond** with the contracts from their respective acceptance criteria.

#### Verification steps (manual)

```powershell
# Boot main_ui
python -m main_ui

# Open in a real browser
start http://127.0.0.1:5001/embed?course=cities_and_climate_change&exercise=04

# Smoke test inside the browser:
# 1. Type "I am starting exercise 4" → click Send
# 2. Observe student bubble appears, "tutor is thinking…" shows, tutor reply renders
# 3. Type "Boston" → press Enter (without Shift)
# 4. Observe second exchange uses the same conversation_id (check network tab payloads)
# 5. Type empty + click Send → nothing happens
# 6. Type "<script>alert(1)</script>" → renders as literal text, no alert
# 7. Type many lines using Shift+Enter, then send → newlines preserved both directions
# 8. Open DevTools → Resize viewport to 320px wide → layout stays usable
# 9. Open DevTools → Application → Cookies → confirm tutor_session_id present
# 10. Open DevTools → Network → confirm /api/chat requests include conversation_id from message 2 onward
```

#### What's deliberately NOT in Step 6

- **No image uploads** (Step 9). The composer is text-only.
- **No email modal** (Step 7). `student_message_count` is captured from responses but not used yet.
- **No history sidebar** (Step 8). New page loads start a fresh conversation; no way to see past ones.
- **No "new conversation" button.** Per meeting notes, each iframe load is a new conversation; refreshing the page is the explicit way to start over.
- **No streaming.** Replies arrive in one chunk after the LLM finishes.
- **No markdown rendering.** Whitespace + line breaks preserved via CSS; bold/italics stay as raw asterisks. Trade-off for keeping the JS small; revisit if students complain.
- **No themes / dark mode.** One light style. Trivial to add later.
- **No tests** (Step 11).
- **No iframe test harness** — Step 10 builds `test_host.html`.

#### Risks / gotchas

- **XSS via `innerHTML`:** never inject tutor or student text via `.innerHTML`. Use `textContent` (or `createTextNode`). Tutor replies are LLM-generated and effectively untrusted; render as text only. Verified by AC14.
- **Auto-scroll fights user scrolling:** if the student scrolls up to re-read an earlier reply, naive auto-scroll yanks them back to the bottom on the next message. Step 6 keeps the simple "always scroll to bottom" behavior — call it out as a known papercut and revisit if it annoys real students during testing.
- **Race on double-clicks:** rapid double-clicks on Send before the disabled state propagates could fire two requests. Set a `is_sending` JS flag and check it at the top of `sendMessage` to short-circuit.
- **Lost text on network error:** the user's draft must NOT be cleared from the textarea on error — only on successful send. Easy to get wrong if `sendMessage` clears the textarea before awaiting the fetch response.
- **Long tutor replies + slow networks:** the fetch has no timeout; if the LLM hangs, the page sits in `sending` forever. Add a client-side timeout (e.g. 60s) and surface a friendly error when it trips.
- **CSP for inline JS:** when we add `Content-Security-Policy` headers later (production hardening), inline `<script>` will be blocked unless explicitly allowed. The `tutor-config` block uses `type="application/json"` which is just data (not executed), so it's fine. The actual `chat.js` is an external file, also fine. No inline event handlers.
- **Mobile-keyboard Enter behavior:** Enter on phone keyboards sometimes means newline, not submit. Keeping the visible Send button means students always have a non-keyboard option.
- **Focus management in iframes:** auto-focusing the textarea works inside an iframe only if the iframe itself has focus. Browsers grant focus on click but not on initial load if the user hasn't clicked into it. Acceptable trade-off; cursor still goes to the textarea once the student clicks anywhere.
- **Long messages clobber the layout:** a 2000-character tutor reply should wrap inside the bubble, not overflow the iframe. Test in a long-reply scenario as part of AC11.
- **No CSRF protection.** `POST /api/chat` accepts any same-origin request without a CSRF token. Iframed cross-origin requests will be blocked by the browser's same-origin policy (the iframe and the API share an origin). For production we'd add SameSite-Strict-style protection or CSRF tokens; not needed for Step 6.

---

## Step 7: Email modal ✦ COMPLETED

**Verified locally** via curl + browser. All API criteria pass: invalid emails return 400 with structured error, valid emails return 200 with `backfilled_conversations` count and set the `tutor_email` cookie (all 6 expected attributes), `data-has-email` body attribute flips from `"false"` to `"true"`, `/api/whoami` reflects the email, idempotent re-submission returns `backfilled_conversations: 0`. Frontend modal triggers after 3rd student message when no cookie, validates `@`+`.` client-side, supports Submit / Skip / Esc / outside-click dismiss. Placeholder copy tweaked to "Enter your email"; tooltip-on-hover suppressed via `title=""` and `type="text"` + `novalidate` (was triggering Firefox's aria-label-as-tooltip behavior).

**Goal:** Capture a best-effort student identifier so we can correlate conversations across the semester (per meeting notes 2026-05-08). After the third student message, show a modal asking for the email the student used to sign up for the course. Validate `@` and `.` client- and server-side. Store the email in the `tutor_email` cookie and on the current Conversation row, then backfill any past Conversations from the same `session_id` that were created before the email was known.

Wrong emails are explicitly accepted as "good enough" per the meeting notes — connections are still useful even if imperfect. This step doesn't verify, send confirmation, or block usage if the modal is dismissed.

#### Files to create

```text
main_ui/
  routes/
    email.py                          # POST /api/email (Blueprint: email_bp)
```

Plus edits to:
- `main_ui/services/conversation.py` — add `backfill_email_for_session(db, session_id, email)`
- `main_ui/run_app.py` — register `email_bp`
- `main_ui/templates/embed.html` — add the modal markup (hidden by default)
- `main_ui/static/css/chat.css` — modal overlay, card, form styles
- `main_ui/static/js/chat.js` — threshold trigger after each chat response, modal show/hide, validation, POST to `/api/email`, cookie-driven re-prompt suppression

#### Purpose of each file

**`main_ui/routes/email.py`**
- **Purpose:** owns `POST /api/email`. Validates the submitted email, sets the `tutor_email` cookie using the same attribute policy as `tutor_session_id`, backfills the current session's past Conversations.
- **Owns:** the `email_bp` Blueprint, request-body validation, and the call into `services/conversation.py::backfill_email_for_session`.
- **Doesn't own:** cookie attribute construction (that's `cookies.py`), the backfill SQL itself (that's `services/conversation.py`).

**`main_ui/services/conversation.py` (modified)**
- **Adds:** `backfill_email_for_session(db, session_id, email) -> int` — updates every `Conversation` row where `session_id` matches and `email IS NULL`, sets `email` to the supplied value, returns the number of rows touched (useful for the response payload + telemetry/debug).
- **Why a helper rather than inline SQL:** keeps DB writes in one module and makes the route handler readable; matches the pattern set in Step 5.

**`main_ui/run_app.py` (modified)**
- **Adds:** `from main_ui.routes.email import email_bp` + `app.register_blueprint(email_bp)`. Nothing else changes — the per-request DB session lifecycle from Step 5 already covers this route.

**`main_ui/templates/embed.html` (modified)**
- **Adds:** a hidden modal block (overlay + card) with email input, Submit, and Skip controls. Lives outside the `<main>` so it can sit above the chat with z-index. The `hidden` attribute keeps it out of the layout until JS shows it.
- **Doesn't add:** any new tutor-config keys; the modal reads no per-render server data.

**`main_ui/static/css/chat.css` (modified)**
- **Adds:** overlay (full-viewport, semi-transparent dark), centered card with rounded corners, email input + Submit button + Skip link styling. Reuses existing CSS variables (`--send-bg`, `--muted`, etc.) for visual consistency.

**`main_ui/static/js/chat.js` (modified)**
- **Adds:**
  - Module-scoped `dismissedThisSession = false` flag (so a Skip click doesn't re-prompt on every subsequent message in the same page load).
  - A `maybeShowEmailModal(student_message_count)` helper called after each successful `/api/chat` response. Conditions to show: count ≥ 3, no `tutor_email` cookie present, and not previously dismissed this session.
  - Modal show/hide functions: trap focus into the email input on open; on close, return focus to the composer.
  - Email format check: regex-light validation matching the server (`@` AND `.`); disables the Submit button until both are present.
  - `POST /api/email` submission with the same error-banner UX pattern used elsewhere.
  - ESC key handler and outside-click handler to dismiss the modal (treated as Skip).
- **Doesn't add:** localStorage-based suppression. Refresh = potentially re-prompt if no cookie yet, by design — students can opt out repeatedly but data capture stays the priority.

#### API spec

**`POST /api/email`**

Request body (JSON):
```json
{ "email": "alice@example.edu" }
```

Successful response (200):
```json
{
  "email": "alice@example.edu",
  "backfilled_conversations": 2
}
```

Error response (400):
```json
{ "error": "invalid_email", "reason": "must contain @ and ." }
```

Side effects:
- Sets `Set-Cookie: tutor_email=alice@example.edu; HttpOnly; SameSite=None; Secure; Partitioned; Max-Age=15552000; Path=/`
- Updates all `conversations` rows where `session_id = g.session_id AND email IS NULL` to set the new email

#### Modal UX

```
+-----------------------------------+
|  [semi-transparent dark overlay]  |
|                                   |
|   +-------------------------+     |
|   |  Help us track your     |     |
|   |  progress               |     |
|   |                         |     |
|   |  Enter the email you    |     |
|   |  used to sign up for    |     |
|   |  this course.           |     |
|   |                         |     |
|   |  [email input         ] |     |
|   |                         |     |
|   |  [Submit]      Skip     |     |
|   +-------------------------+     |
|                                   |
+-----------------------------------+
```

- Overlay covers the iframe; clicking outside the card behaves like Skip.
- Card is centered, capped at ~360px wide, rounded corners.
- Email input is pre-focused on open.
- Submit button is the same crimson as Send, disabled until the input contains both `@` and `.`.
- Skip is a small text-button to the right of Submit (muted color, no background).
- Enter submits when the input is valid; ESC closes (same as Skip).

#### Cookie attribute summary

The `tutor_email` cookie reuses the policy from `cookies.py::default_cookie_kwargs()` — same HttpOnly, SameSite, Secure, Partitioned, Max-Age, Path settings as the session cookie. Server-side helper `default_cookie_kwargs()` is the only source of truth.

#### Threshold + backfill logic

**Threshold (frontend):** after each `/api/chat` response, JS inspects `student_message_count`. If it's ≥ 3, no `tutor_email` cookie is present (read via `document.cookie`), and `dismissedThisSession` is false, the modal opens. Modal opens AFTER the tutor reply renders (since the count comes back in the same response) — so the student isn't interrupted mid-thought.

**Backfill (backend):** when the email is submitted, the backend updates every `Conversation` row with the current `session_id` and a null `email`. This catches:
- The current conversation (created earlier in this iframe load before email was known)
- Any older conversations from the same browser session that were created before this step shipped

New conversations created AFTER email submission already pick up the email from the cookie automatically (Step 5's `chat.py` reads the cookie when creating a Conversation).

#### Dependencies

- No new pip packages.
- Builds on Step 3 (cookie machinery, `EMAIL_COOKIE_NAME` already defined in `cookies.py`), Step 5 (`/api/chat` returning `student_message_count`, Conversation rows already wired to accept an `email` field), and Step 6 (chat UI to attach the modal flow onto).

#### Acceptance criteria

1. **Modal triggers on 3rd message:** after sending 3 student messages in a row from a browser with no `tutor_email` cookie, the modal appears once the third tutor reply renders. Not earlier, not later.
2. **Modal contents:** heading + body + email input + Submit + Skip. Email input is auto-focused.
3. **Validation:** Submit is disabled until the input contains BOTH `@` AND `.`. Typing "bob" leaves it disabled; "bob@example" leaves it disabled (no `.`); "bob.com" leaves it disabled (no `@`); "bob@example.com" enables Submit.
4. **Successful submit:** clicking Submit with a valid email → `POST /api/email` returns 200 → modal closes → `tutor_email` cookie set with all 6 expected attributes → DB rows for the current conversation now have `email` populated.
5. **Backfill:** any older Conversations from the same `session_id` with NULL email are updated to the new email after submission. Response body's `backfilled_conversations` count matches.
6. **Forward-fill:** new Conversations created on subsequent iframe loads (same browser) pick up the email automatically via the cookie at create time (no further backfill needed).
7. **Cookie suppresses re-prompt:** with `tutor_email` cookie set, sending more messages — including across page reloads — never re-shows the modal.
8. **Skip dismisses for the session:** clicking Skip closes the modal; sending more messages in the same page load does not re-show it. A page reload (with no cookie set) can re-prompt.
9. **ESC and outside-click:** both behave like Skip.
10. **Server-side validation:** crafting a request with `{"email": "notanemail"}` directly → 400 with `{"error":"invalid_email","reason":"must contain @ and ."}`. (Client-side disabling stops this in the UI; server-side check guards against direct API calls.)
11. **`/api/whoami` reflects the email:** after submission, `GET /api/whoami` returns the email instead of null.
12. **Steps 1-6 still work:** existing chat flow, message persistence, etc. unaffected.

#### Verification steps (manual)

```powershell
# 1. Fresh start — clear cookies in DevTools first, or use a new browser profile
python -m main_ui
# Open http://127.0.0.1:5001/embed?course=cities_and_climate_change&exercise=01

# 2. Send 3 messages: "hi", "Boston", "what's first?"
# Confirm: modal opens AFTER the 3rd tutor reply renders.

# 3. Try invalid emails: "bob", "bob@example", "bob.com" — Submit stays disabled.

# 4. Try "bob@example.com" — Submit enables. Click Submit.
# Confirm: modal closes; new cookie `tutor_email` visible in DevTools → Storage → Cookies.

# 5. Hit /api/whoami in a new tab — confirm `"email": "bob@example.com"` is returned.

# 6. Inspect the DB to confirm backfill:
python -c "
import main_ui
from main_ui.db import get_session, Conversation
with get_session() as s:
    for c in s.query(Conversation).all():
        print(f'  {c.id} session={c.session_id[:8]} email={c.email}')
"

# 7. Send more messages — confirm modal stays closed.

# 8. Reload the page (Ctrl+R) — start a new conversation — confirm modal does NOT re-open.

# 9. Clear the tutor_email cookie in DevTools, reload, send 3 messages — modal returns.

# 10. Click Skip instead of submitting — modal closes, sending more messages in this page load doesn't re-prompt.
```

#### What's deliberately NOT in Step 7

- **No email verification** — we accept whatever the student types (per meeting notes).
- **No "Resend email" or password-style auth flow** — the email is a soft identifier, not credentials.
- **No localStorage suppression** — refreshing without a cookie can re-prompt (intentional; data capture stays the priority).
- **No email-change flow** — once set, the cookie value is the email until cookie expiry or manual clear. A "change email" feature would belong to a later admin/settings step.
- **No CSP/CORS hardening** for `POST /api/email` — same protections as `POST /api/chat`.
- **No tests** — Step 11.

#### Risks / gotchas

- **HttpOnly cookie can't be read by JS.** The `tutor_email` cookie is `HttpOnly` (matches the session cookie's policy). JS can't read `document.cookie` to check if email is set — it has to ask the server via `/api/whoami` or inspect a flag set on the page server-side. Easiest: on initial page render, embed a `data-has-email="true|false"` attribute on `<body>` based on the request's cookie. Add this when wiring Step 7.
- **Modal pops up mid-typing:** if the student starts typing the 4th message before the 3rd tutor reply arrives, the modal might appear and steal focus while they're typing. Either delay the modal slightly (e.g., 250ms after tutor reply renders) or check whether the textarea has focus and defer. Trade-off; start with the simple "show after reply renders" and refine if it's annoying.
- **`POST /api/email` race:** student opens two iframe tabs and both hit message 3 around the same time, then submits email in tab A. Tab B's modal is still open. After tab B submits, the cookie just gets re-set to the same value (idempotent) — harmless. If they submit different emails, last-write wins. Acceptable for a soft identifier.
- **Lax validation surface:** `@ + .` matches "a@b.c" but also "a@.b" — technically valid by our rule, semantically junk. Per meeting notes this is intentional: we don't gate on stricter regex because data capture > data quality. Document this in the docstring so future maintainers don't "fix" it.
- **Backfill rowcount accuracy:** the SQLAlchemy `update()` query needs `synchronize_session='fetch'` or similar if we want correct rowcount in the same transaction. Note the implementation detail.
- **Modal accessibility:** must add ARIA role="dialog" + `aria-modal="true"` + `aria-labelledby` pointing at the heading. Focus must trap inside the modal until dismissed. Skipping accessibility makes the modal invisible to screen readers and unusable for keyboard-only users. Don't skip.
- **Cookie value containing special chars:** an email like `"alice'); DROP TABLE--"` won't escape into SQL because SQLAlchemy parameterizes, but it WILL go into the cookie verbatim. The browser handles cookie encoding for us via `response.set_cookie`, so this is fine — just worth knowing.
- **`/api/whoami` was returning null for email:** it already reads the `tutor_email` cookie (Step 3 wired this). No code change needed there — just confirm in AC11.

---

## Step 8: Conversation history ✦ ACTIVE

**Goal:** Returning students should see their past tutoring sessions across courses and exercises. After Step 7, the email links sessions together; Step 8 surfaces that link visually as a **collapsed sidebar** listing past conversations, with a **read-only detail view** for inspecting any of them.

Per the 2026-05-08 meeting notes: "When a student clicks the tutor link, a new conversation is created with the exercise as context; previous conversations are shown as history." Past conversations are browsable, not resumable — each iframe load remains a fresh conversation.

This is also the feature explicitly called out in the meeting notes as one MIT can't get from AskTIM today — "cross-exercise history, previous-session context, longitudinal tracking" — so it's the most visible argument for the project's value.

#### Files to create

```text
main_ui/
  routes/
    history.py                        # GET /api/history + GET /api/conversation/<id>
```

Plus edits to:
- `main_ui/services/conversation.py` — add `list_conversations_for_email`, `get_conversation_for_viewer`, `get_messages_for_conversation`
- `main_ui/run_app.py` — register `history_bp`
- `main_ui/templates/embed.html` — sidebar markup + history toggle button + read-only conversation pane
- `main_ui/static/css/chat.css` — sidebar layout (overlay slide-in), entry styling, read-only view styles
- `main_ui/static/js/chat.js` — sidebar toggle, history fetch on open, entry click → detail load + render, "back to current" return path

#### Purpose of each file

**`main_ui/routes/history.py`**
- **Purpose:** owns `GET /api/history` and `GET /api/conversation/<id>`. Both are read-only; neither touches the LLM. Authentication is best-effort — same model as the rest of the app (cookie-based identity, no auth proper).
- **Owns:** the `history_bp` Blueprint, request-shape parsing, ownership checks before exposing detail.
- **Doesn't own:** the DB queries themselves (live in `services/conversation.py`).

**`main_ui/services/conversation.py` (modified)**
- **Adds:**
  - `list_conversations_for_email(db, email) -> list[dict]` — returns conversations for an email, ordered by `last_active_at DESC`. Each entry includes `id`, `course`, `exercise_number`, `tutor_prompt`, `started_at`, `last_active_at`, `message_count`, and a short `first_message_snippet` (truncated to ~80 chars, student-role).
  - `get_conversation_for_viewer(db, conversation_id, session_id, email) -> Conversation | None` — returns the conversation if the viewer either matches `session_id` OR matches `email` (covers both pre-email and post-email access). Returns `None` otherwise.
  - `get_messages_for_conversation(db, conversation) -> list[dict]` — returns `[{turn, role, content}, ...]` in chronological order. Strips `pedagogical_reasoning` from the response (same hide-from-student policy as Step 5).
- **Existing helpers untouched.**

**`main_ui/run_app.py` (modified)**
- **Adds:** `from main_ui.routes.history import history_bp` + `app.register_blueprint(history_bp)`. No other changes.

**`main_ui/templates/embed.html` (modified)**
- **Adds:**
  - A history **toggle button** anchored to the top-left corner of the chat (collapsed icon-only, e.g. ☰ or a clock). Accessible label "View past conversations".
  - A **sidebar `<aside>`** containing a heading ("Past conversations") and an empty `<ul>` that JS populates on first open. Hidden via the same `[hidden]` mechanism the modal uses.
  - A **read-only detail pane** that overlays the live chat when a past conversation is selected. Contains a "Back" button, a header line ("Course · exercise N · started DATE"), and a message-list element styled the same as the live chat but with the composer hidden.
- **Doesn't add:** any inline JS. New `data-*` attributes only if needed for routing.

**`main_ui/static/css/chat.css` (modified)**
- **Adds:**
  - Slide-in sidebar styling (fixed position, left-aligned, full height, ~280px wide on desktop, full-width on narrow iframes; smooth transform transition; semi-transparent backdrop catches outside clicks).
  - History entry styling (clickable rows with course/exercise/date/snippet).
  - Read-only view styles (composer hidden, "back" button visible, optional muted background tint to differentiate from live chat).
  - Toggle button styling (small icon-only button, top-left, doesn't overlap message bubbles).

**`main_ui/static/js/chat.js` (modified)**
- **Adds:**
  - DOM refs for the sidebar, toggle button, entries list, detail pane, back button.
  - `openSidebar()` / `closeSidebar()` — toggle visibility; fetch `/api/history` on first open (or every open — cheap query, no caching for Step 8).
  - `renderHistoryEntries(entries)` — populate the list from API response.
  - `viewConversation(conversationId)` — fetch `/api/conversation/<id>`, render messages in the detail pane, hide live chat composer + message list.
  - `returnToLiveChat()` — hide detail pane, restore live chat view.
  - Escape key + backdrop click close the sidebar (same pattern as the email modal).
- **Doesn't add:** sidebar state persistence across reloads (it's collapsed by default each load).

#### API spec

**`GET /api/history`**

Request: no body, no query params.

Response (200):
```json
{
  "email": "alice@example.edu",
  "conversations": [
    {
      "id": "uuid",
      "course": "cities_and_climate_change",
      "exercise_number": "01",
      "tutor_prompt": "tutor_05",
      "started_at": "2026-05-19T13:00:00+00:00",
      "last_active_at": "2026-05-19T13:12:34+00:00",
      "message_count": 6,
      "first_message_snippet": "I'm starting exercise 1, where do I begin?"
    },
    ...
  ]
}
```

If the request has no `tutor_email` cookie: returns `{"email": null, "conversations": []}` with 200. (We could include conversations linked only by `session_id` here too — see Risks for that decision.)

**`GET /api/conversation/<uuid>`**

Path param: the UUID of the conversation.

Response (200):
```json
{
  "id": "uuid",
  "course": "cities_and_climate_change",
  "exercise_number": "01",
  "tutor_prompt": "tutor_05",
  "started_at": "...",
  "last_active_at": "...",
  "messages": [
    { "turn": 1, "role": "student", "content": "..." },
    { "turn": 1, "role": "tutor",   "content": "..." },
    { "turn": 2, "role": "student", "content": "..." },
    ...
  ]
}
```

Error responses:
- `400` — `<uuid>` isn't a valid UUID
- `404` — conversation doesn't exist OR the viewer has no ownership claim. We deliberately return 404 (not 403) so we don't leak existence to unauthenticated browsers.

Pedagogical reasoning is NOT returned — same policy as `/api/chat` in Step 5.

#### Sidebar UX

```
+-----+------------------------------+
|     |                              |
| ☰   |       chat area              |
|     |                              |
+-----+------------------------------+
```

Closed state: just the icon. Clicking opens:

```
+--------------------+---------------+
| Past conversations |   chat area   |
|  ◦ cities · ex 01  |   (dimmed)    |
|    May 19, 6 msgs  |               |
|    "I'm starting…" |               |
|  ◦ cities · ex 02  |               |
|    May 19, 4 msgs  |               |
|    "What stressors"|               |
+--------------------+---------------+
```

- Slide-in panel from the left (transform: translateX), ~280px wide. On screens < 480px, full-width overlay.
- Semi-transparent backdrop over the chat area (click to close).
- Heading "Past conversations" + close button at top.
- Each entry shows course slug, exercise number, message count, started/last-active date, and a one-line snippet of the first student message.
- Sorted by `last_active_at` descending (most recent first).
- Empty state when no conversations: "No past conversations yet."
- Empty state when no email cookie: "Submit your email to start tracking conversations across exercises."

#### Read-only detail view

When a sidebar entry is clicked, the live chat is replaced with a read-only view:

```
+-----------------------------------+
| < Back                            |
| cities_and_climate_change · ex 01 |
| May 19, 2026 · 6 messages         |
+-----------------------------------+
|                                   |
|   [tutor bubble]                  |
|              [student bubble]     |
|   [tutor bubble]                  |
|              [student bubble]     |
|                                   |
+-----------------------------------+
| (composer hidden in read-only)    |
+-----------------------------------+
```

- "Back" button restores the live chat (whatever in-progress state it had).
- The detail pane mounts inside the same `<main class="chat">` container — composer hidden, message-list replaced. Reverting on Back restores the original DOM.
- No editing, no scrolling-back-into-conversation, no resuming. Pure browsing.

#### Access control logic

For both endpoints, the viewer is identified by two facets stored on `g`:
- `g.session_id` — anonymous cookie identifier (always present after Step 3)
- `g.email` — read from the `tutor_email` cookie in `before_request` (added in Step 7's setup)

Rules:
- `GET /api/history` only lists conversations where `email = g.email`. If no email cookie, returns empty list.
- `GET /api/conversation/<id>` is accessible if the conversation matches either `session_id` (anonymous, same browser) OR `email` (cross-browser via shared email). Otherwise 404.
- We deliberately use 404 instead of 403 for unauthorized access so probing other UUIDs can't distinguish "exists but yours not" from "doesn't exist."

This double-key model means a student with an email cookie set across two browsers (e.g., laptop + phone) sees their full history from either device. A student before submitting their email still sees their own anonymous-session conversations.

#### Dependencies

- No new pip packages.
- Builds on Step 2 (Conversation/Message models), Step 3 (session_id cookie), Step 5 (per-request DB session lifecycle and persisted conversations), Step 6 (chat UI to overlay sidebar onto), Step 7 (email cookie machinery).

#### Acceptance criteria

1. **`GET /api/history` requires no body and returns a JSON object** with `{email, conversations}`.
2. **No email cookie → empty conversations.** Response: `{"email": null, "conversations": []}`.
3. **With email cookie set:** returns all conversations matching that email, ordered by `last_active_at` DESC, each with `id`, `course`, `exercise_number`, `tutor_prompt`, `started_at`, `last_active_at`, `message_count`, `first_message_snippet`.
4. **`first_message_snippet`** is the content of the first `student`-role message in the conversation, truncated to 80 chars with `…` appended if longer. Conversations with no messages get `null`.
5. **`GET /api/conversation/<uuid>`** returns the conversation with its messages array (chronological order, includes turn/role/content; NO pedagogical_reasoning).
6. **`/api/conversation/<id>` 404 for stranger UUID.** Sending a request with a real conversation ID belonging to another session AND a different email returns 404 (not 403).
7. **`/api/conversation/<id>` 400 for bad UUID format.** Path param `"not-a-uuid"` returns 400.
8. **`/api/conversation/<id>` accessible via session_id.** Even before submitting an email, the student can view their own anonymous-session conversations.
9. **Sidebar collapsed by default.** Toggle icon visible at top-left; clicking opens the panel; clicking again or pressing Esc or clicking the backdrop closes it.
10. **Sidebar entries clickable.** Clicking an entry hides the live chat and shows the read-only detail view with all messages in order.
11. **"Back" button restores live chat.** State preserved — the live chat's in-progress messages and conversation_id remain intact.
12. **Composer hidden in detail view.** No way to send messages while viewing a past conversation.
13. **Empty state messaging.** No email + sidebar opened → "Submit your email to track conversations." Email set but no past conversations → "No past conversations yet."
14. **Steps 1-7 still work.** Live chat, email modal, cookie issuance all unchanged.

#### Verification steps (manual)

```powershell
# 1. Fresh DB + start
rm main_ui.db; python -m alembic -c main_ui/db/migrations/alembic.ini upgrade head
python -m main_ui

# 2. Open browser, /embed?course=cities_and_climate_change&exercise=01
#    Send 3 messages so the email modal appears
#    Submit "alice@mit.edu"

# 3. Curl /api/history with the cookie jar to confirm
curl -b "tutor_session_id=...; tutor_email=alice@mit.edu" http://127.0.0.1:5001/api/history

# 4. Reload /embed (or open a new exercise) — sidebar toggle visible.
#    Click toggle → sidebar opens, lists the prior conversation(s).

# 5. Click an entry → read-only view replaces live chat.
#    Verify: messages render in order, composer hidden, "Back" button visible.

# 6. Click Back → live chat restored.

# 7. Curl a random UUID — confirm 404 (not 403, not 500).
curl http://127.0.0.1:5001/api/conversation/00000000-0000-0000-0000-000000000000

# 8. Curl an invalid UUID — confirm 400.
curl http://127.0.0.1:5001/api/conversation/not-a-uuid

# 9. Curl /api/conversation/<real-id> with no cookies — confirm 404 (no ownership claim).
```

#### What's deliberately NOT in Step 8

- **No pagination.** All conversations for the email come back in one shot. Add pagination later if a user hits hundreds of conversations.
- **No search / filtering** in the sidebar (filter by course, by date, by keyword).
- **No conversation resuming.** Past conversations are read-only by design (meeting notes).
- **No editing / deletion of past conversations.** Admin-only concern; out of scope.
- **No bulk export.** Future analytics phase.
- **No real-time updates.** Sidebar re-fetches when opened; doesn't subscribe to updates.
- **No tests** (Step 11).

#### Risks / gotchas

- **Email sharing risk.** If two students share an email (unlikely but possible during testing), they see each other's conversations. Acceptable for a soft identifier per meeting notes. Document, don't fix.
- **Hostile UUID guessing.** Returning 404 (not 403) for unauthorized conversation IDs is the right call — leaks no information about whether the ID exists. Still, a determined attacker could spam UUID guesses; rate limiting is a future concern.
- **Performance with many conversations.** A semester's worth could be 50+ conversations per email. Listing them all in one shot is fine at this scale; if average per-student count grows, add `LIMIT 50` + a "show more" button later.
- **first_message_snippet UTF-8 truncation.** Truncating at 80 chars by `[:80]` could split a multi-byte character. Use a Unicode-safe truncation (e.g., truncate at codepoint boundary, append `…` if longer). Document.
- **Sidebar layout interference on small iframes.** At 320px width, the sidebar should cover the chat (full-width overlay), not push it off-screen. Verify with the test_host iframe at narrow widths in Step 10.
- **DB session held during long sidebar render.** Sidebar fetch is a single SQL query; no LLM call. Should be fast (< 50ms). No need for special handling.
- **State leakage between live chat and detail view.** If the user is mid-send when they click a sidebar entry, the in-flight POST should still complete and update the live chat state (which is hidden but not unmounted). When they click Back, the live chat shows the resolved state. Be careful that the read-only detail view's message-list doesn't share DOM nodes with the live chat.
- **first_message_snippet timing.** If the first message is the only one and it's still in-flight (LLM hasn't replied), the snippet could be incomplete. Acceptable trade-off — query timing is best-effort.
- **Loading state in sidebar.** First open of sidebar triggers a fetch; show a thin "Loading…" line while waiting. Network round-trip is usually fast but should be acknowledged.

---

## Future steps (just placeholders for now)

These will get fleshed out as we work through them. Each maps to the implementation order in [Phase 8 of the main PLANNING.md](../PLANNING.md).

### Step 9: Image uploads

Switch `/api/chat` to `multipart/form-data`. Save uploads under `main_ui/uploads/`, record in `uploaded_images` table. Build multimodal HumanMessage via `utils/figures.py`. Forward to tutor. **Depends on Phase 6** of the main PLANNING.md being implemented.

### Step 10: Test iframe page

Build `main_ui/test_host.html` — a plain HTML page with multiple iframes at different widths pointing at different course/exercise combos. Local dev verification of the embed UX.

### Step 11: Tests + README + documentation

`main_ui/tests/test_routes.py` and `test_models.py`. Flesh out `main_ui/README.md` with the full local dev workflow. Document env vars, migrations, and the `test_host.html` workflow.
