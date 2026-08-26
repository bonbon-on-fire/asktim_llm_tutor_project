# Error Event Log — durable app-wide error capture + internal view

**Date:** 2026-08-26
**Status:** Approved design, pending implementation
**Depends on / relates to:** [2026-08-25-auto-outage-detection-server-design.md](2026-08-25-auto-outage-detection-server-design.md)

## Problem

The auto-outage detector (`service_health`) records only a boolean streak — it
knows *that* the tutor is failing, not *why*. Several failure paths leave no
durable trace at all: the two handled chat failure points (parse-failure /
"Tap to retry", and persist-failure) log nothing, and any unhandled 500 in any
route is gone once the request ends. When a course of hundreds hits trouble,
there is no place an admin can look to see what actually broke.

This feature adds a durable, rolling **error event log** capturing the cause of
every unhandled error (plus the known handled chat failures), and an internal
read-only view of it inside `database_ui`, behind the existing password gate.

It does **not** replace the outage detector. `service_health` stays the banner
trip signal with its curated infra-failure definition; `error_event` is the
human-readable log. The chat failure points write **both**.

## Confirmed decisions

- **Storage:** a new rolling-log table `error_event` (not a column on
  `service_health`).
- **View location:** `database_ui` (the existing read-only admin app).
- **Scope of capture:** app-wide — every unhandled error — plus explicit capture
  at the handled chat failure points that never reach Flask teardown.
- **Tracebacks:** stored, truncated to ~8 KB.
- **Access:** the `/errors` view is **master-login (all-access) only**;
  course-scoped logins do not see it.
- **Dedup:** none in v1 — one row per error. Retention pruning bounds growth.

## Architecture

Three units, mirroring how `service_health` is split:

1. **Write path — main_ui owns it.** A capture service in `main_ui` writes rows
   on a fresh, best-effort session (never recurses, never raises into the
   request). Wired in two ways:
   - **App-wide:** a `teardown_request(exc)` hook installed by the shared
     `ui_core/app_factory.create_app`, but **guarded by an injected
     `error_sink`** — `main_ui` passes a sink; `sandbox_ui` passes none and is
     completely unaffected (same injection style as `maintenance_mode`).
   - **Handled chat failures:** explicit `record_error(...)` calls beside the
     three existing `_record_chat_outcome_safe(False)` sites in
     `main_ui/routes/chat.py` (these are caught in-view during SSE streaming and
     never reach teardown), enriched with course / exercise / conversation id.

2. **Schema — main_ui owns it.** A new Alembic migration (chained off the
   current head `c4e8a1b6d902`) creates the `error_event` table. `database_ui`
   only reads it (no `create_all`, no migrations there — same rule as every
   other table it reads).

3. **Read path / view — database_ui.** A read-only `ErrorEvent` model mirror in
   `database_ui/db/models.py`, a small service (`services/error_events.py`), and
   a new blueprint page `GET /errors` rendering a paginated, filterable,
   newest-first table. Gated master-only inside the view.

### Data flow

```
request → unhandled exception ─────────────► app_factory teardown(exc)
                                                   │ (error_sink set?)
chat SSE stream → handled failure ──► record_error(...) in chat.py
                                                   │
                                                   ▼
                                       main_ui capture service
                                    (fresh session, best-effort,
                                     insert row + prune old rows)
                                                   │
                                                   ▼
                                          error_event  (Postgres)
                                                   │  read-only
                                                   ▼
                              database_ui  /errors  (master-login only)
```

## `error_event` table

| column           | type         | notes                                                        |
|------------------|--------------|--------------------------------------------------------------|
| `id`             | Integer PK   | autoincrement                                                |
| `occurred_at`    | DateTime(tz) | server_default now(); **indexed** (newest-first + `since`)   |
| `source`         | String       | `unhandled` \| `chat_stream` \| `chat_parse` \| `chat_persist` |
| `kind`           | String       | exception class name (e.g. `TimeoutError`, `KeyError`)       |
| `message`        | Text         | exception/reason text, truncated ~2 KB                       |
| `endpoint`       | String, null | Flask endpoint (e.g. `chat.api_chat`)                        |
| `method`         | String, null | HTTP method                                                  |
| `path`           | String, null | request path, **query string stripped** (no PII)            |
| `status_code`    | Integer, null| response status if known                                     |
| `course`         | String, null | chat failures only                                           |
| `exercise`       | String, null | chat failures only                                           |
| `conversation_id`| String, null | chat failures only                                           |
| `traceback`      | Text, null   | formatted stack, truncated ~8 KB                             |

**No student content** is stored — no message text, no uploaded data. `path`
has its query string stripped before storage.

### Retention

Prune-on-write: each insert also best-effort deletes rows older than
`ERROR_LOG_RETENTION_DAYS` (default **14**). No background job (no infra for
one); growth is bounded by the prune. New main_ui config field
`error_log_retention_days` (env `ERROR_LOG_RETENTION_DAYS`, default 14).

## Write path details (main_ui)

New `main_ui/services/error_log.py`:

- `record_error(*, source, exc=None, message=None, endpoint=None, method=None,
  path=None, status_code=None, course=None, exercise=None,
  conversation_id=None, now=None, session_factory=None)` — opens its **own**
  fresh `SessionLocal`, builds the row (deriving `kind`/`message`/`traceback`
  from `exc` when given, applying truncation and query-string stripping),
  inserts, prunes, commits. The whole body is wrapped so **any** failure is
  swallowed with `logger.warning("error_log record skipped", exc_info=True)` —
  logging an error must never break a request or recurse.
- `build_sink()` / the value main_ui passes as `error_sink` — a callable
  `(exc, request_context) -> None` the factory teardown invokes. Reads
  `request.endpoint/method/path` and calls `record_error(source="unhandled",
  ...)`. Guarded so it only fires when `exc is not None`.

`ui_core/app_factory.create_app` gains an optional
`error_sink: Callable | None = None` parameter and, when set, registers:

```python
@app.teardown_request
def _capture_error(exc=None):
    if exc is None or error_sink is None:
        return
    try:
        error_sink(exc, request)
    except Exception:
        pass  # capture must never break teardown
```

`main_ui/run_app.py` passes `error_sink=error_log.build_sink()`;
`sandbox_ui/run_app.py` is unchanged (no sink → hook inert).

Chat failure sites in `main_ui/routes/chat.py` add, next to each existing
`_record_chat_outcome_safe(False)`:
- stream exception (~410): `record_error(source="chat_stream", exc=exc, ...)`
- failed/empty reply (~421): `record_error(source="chat_parse",
  message="tutor returned failed/empty reply", ...)`
- persist failure (~449): `record_error(source="chat_persist", exc=exc, ...)`

each best-effort and enriched with course/exercise/conversation id from the
request scope.

## Read path details (database_ui)

- `database_ui/db/models.py`: add a read-only `ErrorEvent` mapping of the table.
- `database_ui/services/error_events.py`: `list_error_events(db, *, source,
  kind, course, since, limit, offset)` — newest-first, filtered, paged; mirrors
  the `conversations` service and its schema-drift handling.
- New blueprint `errors_bp` (registered in `database_ui/run_app.py`):
  - `GET /errors` — renders `errors.html`: a newest-first table with filter
    controls (`source`, `kind`, `course`, `since`) via query params and simple
    limit/offset paging. Reuses the shell styling.
  - **Master-only gate:** the view checks `allowed_courses() is None`
    (all-access / master / open-dev). A scoped-but-authed login gets `404`
    (hides the page's existence). Unauthed users are already redirected by the
    existing `_require_auth` before_request; the new endpoints are not added to
    `_PUBLIC_ENDPOINTS`.
- New template `database_ui/templates/errors.html`.

## Error handling & edge cases

- **Logging-the-log fails / DB down:** every write is best-effort on a fresh
  session and swallowed. Capture can never amplify an outage or break a request.
- **No recursion:** an exception raised *inside* `record_error` is caught and
  dropped, never re-fed into capture.
- **Error flood during a mass outage:** one row per failed request (the point);
  bounded by prune-on-write. Dedup deferred to a possible v2.
- **The hang case:** a gunicorn-killed worker (120 s hard timeout) runs no
  Python, so a pure hang leaves no `error_event` either — same limitation as the
  detector, same eventual fix (a tutor-call timeout < 120 s). Out of scope here.
- **Sandbox errors:** not captured — `sandbox_ui` may use a different DB and
  `database_ui` reads main_ui's DB. This feature is main_ui-scoped, matching the
  outage feature.
- **Schema drift:** if `database_ui` is deployed reading a DB where the migration
  hasn't run yet, the `/errors` query surfaces the existing "redeploy askTIM-main"
  schema-drift message rather than a raw 500.

## Testing

- **main_ui/services/test_error_log.py** (standalone, in-memory SQLite,
  injected `now`): row is written with derived kind/message/truncated traceback;
  query string stripped; prune deletes rows older than retention and keeps
  recent ones; a raising session_factory is swallowed (returns without raising).
- **main_ui integration** (extend the outage integration harness or a sibling):
  an unhandled 500 in a throwaway route produces an `unhandled` row via the
  factory teardown; each of the three chat failure points produces a row with
  the right `source` and course/exercise context; `sandbox_ui` with no sink
  writes nothing.
- **database_ui**: `list_error_events` filtering/paging/ordering over a seeded
  table; `/errors` returns 200 for a master session, 404 for a scoped session,
  redirect for unauthed; schema-drift path handled.

## Out of scope (v2 candidates)

- Consecutive-identical dedup with occurrence counts.
- Capturing sandbox_ui errors.
- Closing the hang gap (tutor-call timeout) — tracked with the outage feature.
- Alerting / notifications off the log.
