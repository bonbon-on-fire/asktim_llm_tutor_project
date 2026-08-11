# ui_core

Shared web layer the three Flask chat/review apps are built on:
`main_ui` and `sandbox_ui` (the two student-facing chat UIs) and, partially,
`database_ui` (the read-only TA review app). Cookie policy, DB engine/session
plumbing, the SQLAlchemy column mixins for `Message`/`Student`/`UploadedImage`/
`UploadedFile`/`Feedback`, the conversation/image/file/student/feedback
persistence logic, the tutor-bridge control flow, client-side KaTeX math
rendering, and the Flask app-assembly boilerplate all used to be duplicated
across `main_ui` and `sandbox_ui`; this package is the single copy. Each app
still declares its own model classes and thin service wrappers where schemas
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

Shared declarative mixins so `Message`, `Student`, `UploadedImage`,
`UploadedFile`, and `Feedback` aren't redefined per app. Each app still declares the concrete
class on its own `Base` (keeps the table in that app's own `metadata` for
Alembic/`create_all`):

```python
class Message(MessageMixin, Base):
    pass
```

- `StudentMixin` — `students` table: `username` (text PK), `password_hash`,
  `created_at`. Soft-identity proof-of-ownership, not real auth.
- `MessageMixin` — `messages` table: `id` (bigint/int PK), `conversation_id`
  (FK → `conversations.id`, cascade delete), `turn`, `role` (checked
  `student`/`tutor`), `content`, `pedagogical_reasoning` (nullable), `rating`
  (int, default `0`, checked `rating IN (-1, 0, 1)` — per-message thumbs
  down/none/up; legacy rows stored as NULL are treated as `0`), `cost_usd`
  (nullable float — estimated USD cost of producing a tutor turn; NULL on student
  rows / pre-feature rows), `usage_json` (nullable text — the model-id + token
  breakdown backing `cost_usd`, so any figure can be re-derived; parsed via
  `ui_core.usage`), `created_at`; declares the `conversation`, `uploaded_images`,
  and `uploaded_files` relationships plus the role and rating check-constraints
  and an index on `conversation_id`. (`retrieved_context` — the turn's RAG chunks
  as JSON — is declared on each app's own `Message`, not this shared mixin.)
- `UploadedImageMixin` — `uploaded_images` table: `id`, `message_id` (FK,
  cascade delete), `filename`, `mime_type`, `size_bytes`, `data` (raw bytes,
  stored in-DB since Railway's filesystem is ephemeral), `created_at`; declares
  the `message` relationship and an index on `message_id`.
- `UploadedFileMixin` — `uploaded_files` table: `id`, `message_id` (FK,
  cascade delete), `filename`, `kind`, `extracted_text` (plain text re-injected
  into history every turn), `size_bytes`, `data` (raw bytes, stored in-DB same
  as `UploadedImage`), `created_at`; declares the `message` relationship and an
  index on `message_id`. Non-image attachments (csv/xlsx/pdf/etc.).
- `FeedbackMixin` — `feedback` table: `id`, `conversation_id` (FK →
  `conversations.id`, cascade delete), `turn` (nullable int — student-message
  count when the rating was given), `rating` (int, checked `1 <= rating <= 5`),
  `created_at`; index on `conversation_id`. One row per submitted 1–5 star
  tutor rating; not linked to `Message`, only to the conversation as a whole.
  **Now dormant** — per-message thumbs up/down (the `messages.rating` column
  above) replaced the 1–5 star toast; the table/mixin is kept but no longer
  written to by the UIs.
- `_utcnow()` — tz-aware UTC `datetime` default; `_BigIntPk` — `BigInteger`
  that falls back to `Integer` on SQLite (so autoincrement works locally).

**`Conversation` is intentionally NOT shared** — its schema diverges
(`sandbox_ui` adds extra columns), so each app declares its own. `_utcnow`
and `_BigIntPk` are exported from here because every app's own `Conversation`
uses them too.

### `usage.py`

Two dependency-light pure parsers for a tutor message's stored review JSON,
shared by every reader of the `messages` table:

- `model_from_usage_json(usage_json)` — pull the `model` id out of the JSON
  written beside `cost_usd` (model id + token counts); `None` on missing/empty/
  unparseable input
- `records_from_retrieved_context(retrieved_context)` — parse the turn's RAG
  JSON into a `[{source, score, chars, text}]` list; `[]` on missing/empty/
  non-list input

Used by `services/conversation.py`'s `get_messages_for_conversation` **and** by
`database_ui`'s own dependency-minimal service (which can't import
`services/conversation.py` — that pulls in `tutor` — but `ui_core.usage` is
import-light and in database_ui's image), so both parse these columns identically.

### `services/images.py`, `services/files.py`, `services/conversation.py`, `services/students.py`, `services/feedback.py`

App-agnostic persistence logic, parameterized by the caller's own ORM
classes rather than importing them (each app binds its own via a thin
wrapper at `<app>/services/<module>.py`, e.g. `main_ui/services/conversation.py`
binds a `Models(Conversation=..., Message=..., UploadedImage=...)` bundle and
re-exposes the same function names without the `models=` argument).

**`services/files.py`** — mirrors `services/images.py` for non-image
attachments (csv/tsv/xlsx/pdf/docx/txt):
- `read_and_validate(files)` — Flask `FileStorage` list → validated
  attachments via `utils.attachments.validate_files` (reads each upload's
  bytes, then delegates type/size/extraction validation)
- `persist_files(db, *, message, files, uploaded_file_cls)` — insert one
  `UploadedFile` row per validated attachment (filename, `kind`,
  `extracted_text`, bytes), linked to `message`
- `files_to_text(files)` — render validated attachments as labeled text
  blocks (via `utils.attachments.attachments_to_text_block`) for folding into
  the current turn's tutor message

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
  `[{role, content}, ...]`, shaped for `tutor_bridge`. Each past student turn's
  `uploaded_files` extracted text is re-injected into `content` as
  `\n\n[Attachment: <name>]\n<text>` (model-facing only — the stored/displayed
  message stays plain text), batch-loaded per conversation via
  `_files_by_message` to avoid N+1 lookups (mirrors `_images_by_message`); a
  no-op when the app doesn't bind `UploadedFile`
- `get_cached_history_for_tutor(db, conversation, *, models)` — the cache-friendly
  counterpart to `get_history_for_tutor`, used when `cached_history_enabled()`
  (the default). Returns one `{student_content, rag_text, tutor_json}` dict per
  prior **completed** turn (student + tutor message both present): `rag_text`
  re-renders that turn's persisted `Message.retrieved_context` records back into
  the same formatted block via `rag.retrieve.format_context` (empty when there
  was none), and `tutor_json` is the canonical verbatim
  `{"pedagogical-reasoning": ..., "Student-facing-answer": ...}` string
  (`tutor.cached_history.tutor_output_json`) — so replay is byte-stable across
  turns. Feeds `tutor.cached_history.build_message_plan()` via `tutor_bridge`
- `count_student_messages(db, conversation, *, models)` — used to trigger the
  username modal at 3 student messages
- `list_conversations_for_username(db, username, *, models, summarize_extra=None)`
  and `get_conversation_for_viewer(db, conversation_id, session_id, username, *, models)`
  — history/detail read paths; `summarize_extra` lets `sandbox_ui` merge extra
  summary keys
- `get_messages_for_conversation(db, conversation, *, models, include_reasoning=False, include_retrieved=False, include_cost=False)`
  — `sandbox_ui` passes all three flags on (dev/TA tool); `main_ui` leaves them
  off (student-facing policy). Each message dict always carries `id` and `rating`
  (so the client can render and toggle the thumbs control); `include_reasoning`
  adds `pedagogical_reasoning`, `include_retrieved` adds the turn's RAG `retrieved`
  chunks, and `include_cost` adds `cost_usd` plus the `model` id (both parsed via
  `ui_core.usage`). The read-only `database_ui` service produces the same shape
  from its own models.
- `get_message_for_viewer(db, message_id, session_id, username, *, models)` —
  return a `Message` only if the viewer owns its parent conversation (by
  `session_id` or matching `username`), else `None`; mirrors
  `get_conversation_for_viewer` so rating routes 404 without leaking existence
- `set_message_rating(db, message, rating)` — set a message's `rating` to
  `-1`/`0`/`1` (used by the message-rating blueprint)
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

**`services/feedback.py`** (dormant — superseded by per-message ratings)
- `record_feedback(db, *, conversation_id, turn, rating, feedback_cls)` —
  insert one `Feedback` row (rating 1..5, `turn` nullable) linked to a
  conversation. Kept but no longer called now that the star toast UI is gone.

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
  `about_asktim.txt` + the `pinned/*.txt` reference docs (course description,
  syllabus, and any other always-on material) + optional lecture transcripts +
  `exercise_<NN>.txt`, then, when a matching solution file exists, the current
  problem's paired **correct answer & worked solution** as a tutor-only reference
  block (via `utils.curriculum.read_solution`, keyed by problem number —
  deterministic, never retrieved, never shown to the student). The `pinned/*.txt`
  docs (via `utils.curriculum.read_pinned_context`) are **pinned in both
  `full_context` and `rag`** — and correspondingly **excluded from the RAG index**
  (see `rag/sources.py`) so nothing pinned is also retrieved. Lecture transcripts
  (large) are baked in only in `full_context`; in `rag` they're reached via
  retrieval. `exercise_only` drops all course material (about-block + exercise only)
- `build_system_prompt(tutor, assignment_text, course="", **ctx)` — wraps the
  assignment text into a full system prompt via `tutor.run_tutor.load_system_prompt`,
  then appends the course's `curriculum/<course>/tutor_rules.txt` (if any) via
  `utils.curriculum.append_course_tutor_rules` — a course-specific rules delta on
  top of the shared base prompt (`tutor_08`), so no per-course prompt fork is needed
- `retrieved_context(course, query, **ctx)` — per-turn RAG retrieval, returned as
  a `RetrievedContext(text, records)` dataclass: `.text` is the formatted block
  that always rides in the tutor's **system** channel, never onto the student's
  turn. By default (cache-friendly history) it becomes its own interleaved
  system message right after that turn's student message; under the legacy
  `TUTOR_CACHED_HISTORY=0` fallback it's appended after the static cacheable
  prompt instead (see [What the tutor receives each turn](#what-the-tutor-receives-each-turn)
  below). `.records` is `[{source, score, chars, text}]` (what RAG pulled, for
  persistence/inspection, and — for cache-friendly history — replayed to
  re-render this turn's RAG block on later turns). Empty by default (sandbox's
  RAG mode fills it in)
- `turn_attachments(course, exercise, images, **ctx)` — curriculum figures (via
  `utils.figures.discover_figures`) + uploaded images to attach to the latest
  student turn; `None` when there's nothing to attach

Public API:
- `get_tutor_reply(*, course, exercise, tutor, history, new_student_message, images=None, **ctx)`
  → `{"reply": str, "reasoning": str | None, "retrieved": list}` (`retrieved` is
  the `RetrievedContext.records` for the turn — `[]` outside RAG mode)
- `stream_tutor_reply(..., history_mode="legacy", cached_history=None)` — generator
  yielding `{"type": "delta", "text": ...}` events, then one terminal
  `{"type": "done", "reply": ..., "reasoning": ..., "retrieved": ..., "cost": ...}`.
  Callers pass `history_mode="cached"` (the default in both chat apps, gated by
  `cached_history_enabled()`) plus `cached_history` — the per-turn
  `{student_content, rag_text, tutor_json}` rows from
  `ui_core.services.conversation.get_cached_history_for_tutor` — to drive the
  interleaved, cache-friendly path; `history_mode="legacy"` (or omitting it)
  uses the flat `history` list from `get_history_for_tutor` instead.

**System-message assembly** — by **default** (cache-friendly history, gated by
`TUTOR_CACHED_HISTORY`; see `cached_history_enabled()` above),
`tutor.cached_history.build_message_plan()` places each turn's retrieved RAG
material (the `RetrievedContext.text`, framed via `_retrieved_context_block` /
the module constant `RETRIEVED_CONTEXT_HEADER`) as its **own** system message
interleaved right after that turn's student message, with the current turn's
retrieved block coming last. The plan is sent through the raw `anthropic` SDK
for Claude (`langchain_anthropic` rejects multiple non-consecutive system
messages) or as interleaved `SystemMessage`s via langchain for GPT (which
accepts them).

Under the legacy `TUTOR_CACHED_HISTORY=0` fallback,
`_build_system_message(system_prompt, model, retrieved_context)` instead folds
the turn's retrieved RAG material into the single leading system message,
appended **after** the static cacheable prompt — a second, **uncached** text
block after the `cache_control` breakpoint for Anthropic, or appended to the
system string for OpenAI — so the static prefix still auto-caches, though the
growing history itself does not.

Either way, retrieved material rides in the **system** message — not a
"developer" message, since LangChain has no developer role — and never on the
student's turn (which stays clean).

### What the tutor receives each turn

**By default** (cache-friendly history, gated by `TUTOR_CACHED_HISTORY` — see
`cached_history_enabled()` above), the streaming path interleaves the turns
rather than sending three flat blocks: a leading **system** message carries
the tutor prompt with the assignment context baked in (the `pinned/*.txt` docs —
course description, syllabus — in `full_context`/`rag`, lecture transcripts in
`full_context` only, the exercise, the tutor-only answer key); then, for each prior turn, the student's message, that
turn's retrieved RAG as its own **system** message (when there was any), and
the tutor's **verbatim past reply** — the full `pedagogical-reasoning` +
`Student-facing-answer` JSON, not just the student-facing text; then the
**current student turn** (their text plus any attached figures/uploaded
files), followed by the current turn's retrieved RAG as the last message.
Because every replayed rag/tutor block is byte-identical turn to turn, the
tutor's own past reasoning **is** replayed back to it — intentional, so the
prefix stays stable for caching and few-shots the JSON output format — and the
whole conversation history becomes cacheable, not just the static prompt.

Set `TUTOR_CACHED_HISTORY=0`/`false`/`no`/`off` to fall back to the legacy
shape (also always used by the non-streaming `get_tutor_reply` path): one
**system** message (tutor prompt + assignment context, with any per-turn RAG
appended after the cacheable prompt), then the **conversation history** as
prior student messages and the tutor's student-facing answers only, with the
hidden pedagogical-reasoning **stripped** — the tutor never re-receives its own
past reasoning in this mode — then the **current student turn**.

Either way, retrieved material always arrives as background in the system
channel rather than as the student's words.

`main_ui` uses `TutorBridge` directly; `sandbox_ui` subclasses it.

### `web/static_blueprint.py`

`static_bp` — a Flask `Blueprint` named `"ui_core"` serving `ui_core/static/`
at `/ui-core`: `css/chat.css`, vendored **KaTeX 0.16.11** (`css/katex.min.css`
+ `css/fonts/*` + `js/katex.min.js`), and `js/katex-marked.js` (see
`templates/base_chat.html` below). `database_ui` (which doesn't use
`app_factory`) registers this blueprint directly so its login-gate allowlist
can carve out `ui_core.static` as a public endpoint (the login page itself
needs `chat.css`).

### `static/js/katex-marked.js`

Client-side math rendering, shared by all three chat UIs (main_ui, sandbox_ui,
database_ui). Exposes a browser global (and CommonJS export for
`test_katex_marked.js`):

- `renderTutorMarkdown(content)` — parses `content` with `marked`, using a
  `marked` extension (`makeMathExtension`) that recognizes `\(...\)` (inline)
  and `\[...\]` (display) as KaTeX math and renders them with
  `katex.renderToString`; `$...$` is deliberately **not** treated as math
  (it's currency in this course). Falls back to plain `marked.parse` if KaTeX
  isn't loaded, and to `null` (caller renders as plain text) if `marked` or
  `DOMPurify` isn't loaded. The resulting HTML is always run through
  `DOMPurify.sanitize` before use. Each app's `chat.js` calls this from
  `setMessageContent` instead of a bare `marked.parse`/`textContent` render.

### `web/blueprints/identity.py`, `web/blueprints/history.py`, `web/blueprints/feedback.py`, `web/blueprints/message_rating.py`

Blueprint factories, byte-identical in body across `main_ui`/`sandbox_ui`
apart from import paths — each app injects its own `cookies` /
`services.conversation` / `services.students` / `services.images` /
`services.feedback` modules (passed as plain modules, not classes) so the
shared route bodies stay app-agnostic. Blueprint names are preserved as
`identity`, `history`, `feedback`, and `message_rating`.

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

**`make_feedback_bp(*, cookies, conversation, feedback)`** → blueprint named
`feedback` (**dormant** — kept registered but the star toast UI that drove it
was removed; superseded by `make_message_rating_bp`):
- `POST /api/feedback` — record a 1..5 star rating for a conversation owned
  by the current session (`session_id` or matching `username`). Body:
  `{conversation_id, rating, turn?}`. 400 on a missing/malformed
  `conversation_id` or an out-of-range/non-integer `rating`; 403
  (`wrong_session`) if the conversation isn't found or isn't owned by the
  caller.

**`make_message_rating_bp(*, cookies, conversation)`** → blueprint named
`message_rating`:
- `POST /api/message/<id>/rating` — set the thumbs rating on a single message.
  Body: `{"rating": -1|0|1}`. Owner-only (via `get_message_for_viewer`, so a
  message the caller doesn't own 404s) and **tutor-only** (only the tutor's
  messages are rateable). Persists via `set_message_rating`.

### `templates/base_chat.html`

The shared page shell (head, sidebar, message list, composer, image-attach
modal, username/password modal, and the KaTeX + `katex-marked.js` script/link
tags) that each app's own `embed.html` extends: `{% extends "base_chat.html" %}`.
The old star `feedback-toast` markup has been removed; per-message thumbs
up/down controls take its place, and `chat.css` swaps the old star styles for
`.msg-rating`/`.rating-btn`. Exposes override
blocks (`title`, `head_extra`, `banner`, `beta_tag`, `sidebar_cta_extra`,
`modals_extra`, `chat_js_src`) for per-app customization.

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

A few smaller, newer tests at the package root deviate from the
`_check`/`main()` convention above and use plain pytest-style `assert`
functions instead: `test_files_service.py` (`services/files.py`'s
`read_and_validate`/`files_to_text`), `test_history_injection.py`
(`services/conversation.py`'s `_content_with_attachments` helper behind
`get_history_for_tutor`'s attachment re-injection), and
`test_uploaded_file_model.py` (imports `sandbox_ui.db.models.UploadedFile` —
another exception to the "no app imports" rule — to assert the
`UploadedFileMixin` columns are present). Run with `pytest` rather than `python -m`.
KaTeX rendering (`static/js/katex-marked.js`) has its own Node test,
`static/js/test_katex_marked.js` (`node --test`), covering inline/display
math rendering and that `$...$` currency stays literal.

## How the apps consume it

- `main_ui` and `sandbox_ui` call `ui_core.app_factory.create_app(...)` from
  their `run_app.py` to build the Flask app, register `identity`/`history`/
  `feedback`/`message_rating` blueprints built via `make_identity_bp`/
  `make_history_bp`/`make_feedback_bp`/`make_message_rating_bp` (the
  `feedback` one now dormant), extend `base_chat.html` in their own `embed.html`,
  declare their own `Conversation` class (`Message`/`Student`/`UploadedImage`/
  `UploadedFile`/`Feedback` via the shared mixins), build their engine with
  `build_engine(url, sqlite_fk=True)`, and keep thin
  `services/{conversation,images,files,students,feedback,tutor_bridge}.py`
  wrappers that bind their model classes into the shared, model-agnostic
  functions above. `sandbox_ui`'s `tutor_bridge.py` subclasses `TutorBridge`
  (`SandboxTutorBridge`) to add RAG/context-mode/reasoning-toggle behavior.
- `database_ui` only partially depends on `ui_core`: it uses
  `build_engine`/`make_session_factory`/`session_scope` directly (with
  `pool_pre_ping=True, normalize_pg=True`, and always `read_only=True`),
  registers `static_bp` directly so its auth gate can allowlist
  `ui_core.static` as a public endpoint, and imports `ui_core.usage` for the
  message JSON parsers. It does not use `app_factory`, the identity/history
  blueprints, the model mixins, or `tutor_bridge` — it has no chat and no
  student-identity linking of its own.
