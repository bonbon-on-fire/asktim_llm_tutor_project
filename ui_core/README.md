# ui_core

Shared web layer the three Flask chat/review apps are built on:
`main_ui` and `sandbox_ui` (the two student-facing chat UIs) and, partially,
`database_ui` (the read-only TA review app). Cookie policy, DB engine/session
plumbing, the SQLAlchemy column mixins for `Message`/`Student`/`UploadedImage`,
the conversation/image/student persistence logic, the tutor-bridge control
flow, and the Flask app-assembly boilerplate all used to be duplicated across
`main_ui` and `sandbox_ui`; this package is the single copy. Each app still
declares its own model classes and thin service wrappers where schemas
diverge (see per-module notes below) — `ui_core` never imports an app
package, only the reverse.

## Modules

### `cookies.py`

Single source of truth for cookie names and the attribute policy applied to
`response.set_cookie(...)`.

- `SESSION_COOKIE_NAME` = `"tutor_session_id"`, `USERNAME_COOKIE_NAME` =
  `"tutor_username"`
- `new_session_id()` — fresh anonymous session id (UUIDv4 string)
- `default_cookie_kwargs(*, secure, max_age)` — `HttpOnly`, `SameSite=None`,
  `Secure`, `Partitioned` (CHIPS), `path="/"`; `secure` and `max_age` are
  supplied by each app's own config

### `db/session.py`

Engine/session helpers parameterized by the behavior knobs each app needs:

- `normalize_pg_url(url)` — rewrites `postgres://` / `postgresql://` to
  `postgresql+psycopg://` so SQLAlchemy uses psycopg3
- `build_engine(database_url, *, sqlite_fk=False, pool_pre_ping=False, normalize_pg=False)`
- `make_session_factory(engine)` — `sessionmaker(expire_on_commit=False, future=True)`
- `session_scope(session_factory, *, read_only=False)` — context manager
  yielding a `Session`; commits on success unless `read_only`, rolls back on
  error, always closes

Per-app flags actually passed:

| App | `sqlite_fk` | `pool_pre_ping` | `normalize_pg` | `read_only` |
| --- | --- | --- | --- | --- |
| `main_ui` | `True` | — | — | — |
| `sandbox_ui` | `True` | — | — | — |
| `database_ui` | — | `True` | `True` | `True` (every `get_session()` call) |

`main_ui`/`sandbox_ui` enable SQLite FK enforcement for local dev; `database_ui`
guards a long-lived remote Postgres connection and never writes.

### `db/models_common.py`

Shared declarative mixins so `Message`, `Student`, and `UploadedImage` aren't
redefined per app. Each app still declares the concrete class on its own
`Base` (keeps the table in that app's own `metadata` for Alembic/`create_all`):

```python
class Message(MessageMixin, Base):
    pass
```

- `StudentMixin` — `students` table: `username` (text PK), `password_hash`,
  `created_at`. Soft-identity proof-of-ownership, not real auth.
- `MessageMixin` — `messages` table: `id` (bigint/int PK), `conversation_id`
  (FK → `conversations.id`, cascade delete), `turn`, `role` (checked
  `student`/`tutor`), `content`, `pedagogical_reasoning` (nullable),
  `created_at`; declares the `conversation` and `uploaded_images`
  relationships plus the role check-constraint and an index on
  `conversation_id`.
- `UploadedImageMixin` — `uploaded_images` table: `id`, `message_id` (FK,
  cascade delete), `filename`, `mime_type`, `size_bytes`, `data` (raw bytes,
  stored in-DB since Railway's filesystem is ephemeral), `created_at`; declares
  the `message` relationship and an index on `message_id`.
- `_utcnow()` — tz-aware UTC `datetime` default; `_BigIntPk` — `BigInteger`
  that falls back to `Integer` on SQLite (so autoincrement works locally).

**`Conversation` is intentionally NOT shared** — its schema diverges
(`sandbox_ui` adds extra columns), so each app declares its own. `_utcnow`
and `_BigIntPk` are exported from here because every app's own `Conversation`
uses them too.

### `services/images.py`, `services/conversation.py`, `services/students.py`

App-agnostic persistence logic, parameterized by the caller's own ORM
classes rather than importing them (each app binds its own via a thin
wrapper at `<app>/services/<module>.py`, e.g. `main_ui/services/conversation.py`
binds a `Models(Conversation=..., Message=..., UploadedImage=...)` bundle and
re-exposes the same function names without the `models=` argument).

**`services/images.py`**
- `read_and_validate(files)` — Flask `FileStorage` list → validated images via
  `utils.uploads.validate_images` (raises `UploadValidationError`)
- `persist_images(db, *, message, images, uploaded_image_cls)` — insert one row
  per validated image, linked to `message`
- `get_image_for_viewer(db, image_id, session_id, username, *, uploaded_image_cls, message_cls, conversation_cls)`
  — return the image only if the viewer owns its parent conversation (by
  `session_id` or matching `username`), else `None` (so routes 404 without
  leaking existence)

**`services/conversation.py`**
- `Models` — frozen dataclass bundling `Conversation`/`Message`/`UploadedImage`
  classes for a given app
- `WrongSessionError` — raised when a supplied `conversation_id` doesn't exist
  or isn't owned by the current session
- `find_or_create_conversation(db, *, models, session_id, conversation_id, course, exercise_number, tutor_prompt, username=None, extra_fields=None)`
- `append_exchange(db, *, models, conversation, student_text, tutor_text, pedagogical_reasoning)`
  — insert the student+tutor message pair for one turn
- `start_exchange_student_only` / `complete_exchange_tutor` — split version of
  `append_exchange` used by the SSE streaming chat path (student row persisted
  before streaming begins; tutor row added once the stream completes)
- `get_history_for_tutor(db, conversation, *, models)` — prior messages as
  `[{role, content}, ...]`, shaped for `tutor_bridge`
- `count_student_messages(db, conversation, *, models)` — used to trigger the
  username modal at 3 student messages
- `list_conversations_for_username(db, username, *, models, summarize_extra=None)`
  and `get_conversation_for_viewer(db, conversation_id, session_id, username, *, models)`
  — history/detail read paths; `summarize_extra` lets `sandbox_ui` merge extra
  summary keys
- `get_messages_for_conversation(db, conversation, *, models, include_reasoning=False)`
  — `sandbox_ui` passes `include_reasoning=True` (dev/TA tool), `main_ui`
  excludes the tutor's hidden reasoning (student-facing policy)
- `backfill_username_for_session(db, session_id, username, *, models)` —
  retroactively links a session's anonymous conversations to a username
- internal: `_images_by_message`, `_summarize_conversation`, `_next_turn_number`

**`services/students.py`**
- `MIN_PASSWORD_LENGTH` = 6; `WeakPasswordError`
- `get_student(db, username, *, student_cls)`
- `create_student(db, *, username, password, student_cls)` — bcrypt-hashes the
  password; raises `WeakPasswordError` if too short
- `verify_password(student, password)` — bcrypt check, `False` (not a raise)
  on malformed stored hash

### `tutor_bridge.py`

`TutorBridge` — the base class carrying `main_ui`'s behavior as the default;
`sandbox_ui`'s `SandboxTutorBridge` subclasses it to layer RAG / custom-context
/ reasoning-toggle behavior on the same control flow. No HTTP, no DB, no Flask
state — just `(course, exercise, tutor, history, new_student_message)` →
tutor reply. Each instance owns its own graph/stream caches.

Overridable hooks (defaults shown are the base/`main_ui` behavior):
- `prepare_ctx(course, **ctx)` — resolve/normalize per-app extra kwargs before
  they thread through the rest of the call; no-op in the base
- `cache_key(tutor, course, exercise, **ctx)` — key for the graph/stream
  caches; return `None` to skip caching for that call (sandbox does this for
  one-off custom context)
- `build_assignment_text(course, exercise, **ctx)` — concatenates
  `about_asktim.txt` + `course.txt` + optional `syllabus.txt` + optional
  lecture transcripts + `exercise_<NN>.txt`
- `build_system_prompt(tutor, assignment_text, **ctx)` — wraps the assignment
  text into a full system prompt via `tutor.run_tutor.load_system_prompt`
- `retrieved_context(course, query, **ctx)` — per-turn RAG context prepended to
  the student message; empty string by default (sandbox's RAG mode fills it in)
- `turn_attachments(course, exercise, images, **ctx)` — curriculum figures (via
  `utils.figures.discover_figures`) + uploaded images to attach to the latest
  student turn; `None` when there's nothing to attach

Public API:
- `get_tutor_reply(*, course, exercise, tutor, history, new_student_message, images=None, **ctx)`
  → `{"reply": str, "reasoning": str | None}`
- `stream_tutor_reply(...)` (same signature) — generator yielding
  `{"type": "delta", "text": ...}` events, then one terminal
  `{"type": "done", "reply": ..., "reasoning": ...}`

`main_ui` uses `TutorBridge` directly; `sandbox_ui` subclasses it.

### `web/static_blueprint.py`

`static_bp` — a Flask `Blueprint` named `"ui_core"` serving `ui_core/static/`
(currently just `css/chat.css`) at `/ui-core`. `database_ui` (which doesn't use
`app_factory`) registers this blueprint directly so its login-gate allowlist
can carve out `ui_core.static` as a public endpoint (the login page itself
needs `chat.css`).

### `web/blueprints/identity.py`, `web/blueprints/history.py`

Blueprint factories, byte-identical in body across `main_ui`/`sandbox_ui`
apart from import paths — each app injects its own `cookies` /
`services.conversation` / `services.students` / `services.images` modules
(passed as plain modules, not classes) so the shared route bodies stay
app-agnostic. Blueprint names are preserved as `identity` and `history`.

**`make_identity_bp(*, cookies, conversation, students)`** → blueprint named
`identity`:
- `GET /api/whoami` — current `session_id`/`username`
- `POST /api/identity/check` — probe whether a username has a password
  registered yet (drives the two-step login modal)
- `POST /api/identity` — link the session to a username+password (creates the
  student on first use, verifies password thereafter, 401 on mismatch); sets
  the `tutor_username` cookie and backfills prior anonymous conversations

**`make_history_bp(*, cookies, conversation, images)`** → blueprint named
`history`, all read-only:
- `GET /api/history` — conversations linked to the current `tutor_username`
- `GET /api/conversation/<uuid>` — message log for one conversation (owned by
  session_id or username; 404, not 403, on mismatch/absence)
- `GET /api/image/<int:image_id>` — serve one uploaded image's bytes (same
  ownership check)

### `templates/base_chat.html`

The shared page shell (head, sidebar, message list, composer, image-attach
modal, username/password modal, markdown-rendering script tags) that each
app's own `embed.html` extends: `{% extends "base_chat.html" %}`. Exposes
override blocks (`title`, `head_extra`, `banner`, `beta_tag`,
`sidebar_cta_extra`, `modals_extra`, `chat_js_src`) for per-app customization.

### `app_factory.py`

`create_app(*, import_name, config, service_name, session_local, blueprints, on_startup=None)`
— collapses the boilerplate that used to be duplicated across `main_ui` and
`sandbox_ui`'s `run_app.py`. Wires:

- `app.config["SECRET_KEY"]` from `config.secret_key`
- a `ChoiceLoader` combining the app's own Jinja loader with a
  `FileSystemLoader` over `ui_core/templates`, so `{% extends "base_chat.html" %}`
  resolves
- registers `static_bp` (`/ui-core`) plus every blueprint passed in
- `before_request` hooks: resolve/create `g.session_id` from the
  `tutor_session_id` cookie, and open `g.db = session_local()`
- `teardown_request`: commits (or rolls back on exception) and closes `g.db`
  — a no-op if a route already popped `g.db` itself (the streaming `/api/chat`
  route manages its own session lifecycle)
- `after_request`: sets the session cookie only when the session id was newly
  minted this request
- `GET /health` → `{"status": "ok", "service": service_name}`
- runs `on_startup()` if given, then returns the built `Flask` app

`database_ui` is structurally different (read-only, password-gated, no chat)
and does not use this factory — it registers `static_bp` directly instead.

### Tests (`test_*.py`)

Every module has a standalone `test_<module>.py` — **no pytest**. Each defines
a `_check(name, condition, detail="")` helper that prints `PASS`/`FAIL`, and a
`main()` that runs the module's test functions and returns a non-zero exit
code if anything failed. Run one with:

```powershell
python -m ui_core.test_cookies
python -m ui_core.test_tutor_bridge
python -m ui_core.db.test_session
python -m ui_core.db.test_models_common
python -m ui_core.services.test_conversation
python -m ui_core.services.test_images
python -m ui_core.services.test_students
python -m ui_core.web.test_static_blueprint
```

Model/session-dependent tests build their own local `Base`/model classes
(SQLite in a temp dir) rather than importing an app's models, since `ui_core`
must not depend on the app packages. `test_tutor_bridge.py` is the one
exception that imports an app module (`sandbox_ui.services.tutor_bridge`) so
it can exercise the base/subclass split side by side; it stubs out every
upstream LLM/graph call, so it stays fully offline.

## How the apps consume it

- `main_ui` and `sandbox_ui` call `ui_core.app_factory.create_app(...)` from
  their `run_app.py` to build the Flask app, register `identity`/`history`
  blueprints built via `make_identity_bp`/`make_history_bp`, extend
  `base_chat.html` in their own `embed.html`, declare their own `Conversation`
  class (`Message`/`Student`/`UploadedImage` via the shared mixins), build
  their engine with `build_engine(url, sqlite_fk=True)`, and keep thin
  `services/{conversation,images,students,tutor_bridge}.py` wrappers that bind
  their model classes into the shared, model-agnostic functions above.
  `sandbox_ui`'s `tutor_bridge.py` subclasses `TutorBridge`
  (`SandboxTutorBridge`) to add RAG/context-mode/reasoning-toggle behavior.
- `database_ui` only partially depends on `ui_core`: it uses
  `build_engine`/`make_session_factory`/`session_scope` directly (with
  `pool_pre_ping=True, normalize_pg=True`, and always `read_only=True`), and
  registers `static_bp` directly so its auth gate can allowlist
  `ui_core.static` as a public endpoint. It does not use `app_factory`, the
  identity/history blueprints, the model mixins, or `tutor_bridge` — it has no
  chat and no student-identity linking of its own.
