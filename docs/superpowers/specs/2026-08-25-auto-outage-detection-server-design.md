# Automatic outage detection — server-side (phase 2)

Date: 2026-08-25
Scope: `main_ui` (production tutor). Complements phase 1 (client-side
detection in `main_ui/static/js/outage_monitor.js`, commit `1ce76257`).

## Problem

During large courses, when the tutor pipeline is down or unresponsive,
students see a hanging/failing chat with no explanation and email support in
bulk. The "AskTIM is temporarily down" overlay exists but is driven only by the
`MAIN_UI_MAINTENANCE` env var, read once at startup — a human must notice the
outage and redeploy to flip it. Phase 1 shows the note client-side after a
per-browser failure streak, but cannot show it on a *fresh* page load and each
browser only sees its own experience. Phase 2 adds an authoritative,
server-derived signal.

## Constraints (from the codebase)

- **4 gunicorn workers, single replica, no Redis** (`scripts/railway-entrypoint-main.sh`).
  Cross-worker shared state must be Postgres (`DATABASE_URL`).
- **Alembic migrations** run on every deploy via the entrypoint; there is no
  boot-time `create_all` in production. A new table needs a revision chained off
  head `b3d9f1a4c027`.
- `/health` is a static liveness probe and is allow-listed during maintenance.
- The LLM is Anthropic (tutor) + OpenAI embeddings (RAG). Synthetic LLM pings
  are costly / rate-limit-prone, so detection avoids them.

## Decisions (approved)

- **Passive real-traffic detection.** Real `/api/chat` outcomes are the signal;
  no synthetic probes, no background thread, no leader election.
- **Banner only.** The auto-degraded flag drives the overlay on page loads; it
  does **not** 503 the chat API. The hard 503 block stays the manual
  `MAIN_UI_MAINTENANCE`. Keeping the API reachable lets a recovered service
  self-clear and bounds the damage of a false positive.

## Design

### 1. `service_health` table (singleton, id=1)

New SQLAlchemy model + Alembic revision (down_revision `b3d9f1a4c027`). The
migration seeds the single row. Columns:

- `id` (PK, always 1)
- `degraded` (bool, default false)
- `degraded_since` (datetime, nullable)
- `consecutive_failures` (int, default 0)
- `last_success_at` / `last_failure_at` (datetime, nullable)
- `updated_at` (datetime)

### 2. Outcome recorder — `main_ui/services/service_health.py`

`record_chat_outcome(db, ok: bool)` — called best-effort from the chat route
(wrapped so a health-tracking failure never breaks a chat). One atomic UPDATE so
the 4 workers don't race:

- `ok=True`  → `consecutive_failures=0`, `degraded=false`, `degraded_since=null`,
  set `last_success_at`.
- `ok=False` → `consecutive_failures = consecutive_failures + 1`,
  set `last_failure_at`; if the new value `>= SERVER_FAILURE_THRESHOLD` (default
  5) set `degraded=true`, `degraded_since=now` (only when not already degraded).

Threshold 5 (vs phase 1's 3) because this aggregates *all* students — 5 failures
in a row with zero successes between is a strong global-outage signal.

Which `/api/chat` outcomes count as an infra failure vs. a user error mirrors
phase 1 exactly (5xx / server error frame / empty stream / transport error =
failure; login/too-long/limit and intentional aborts are excluded).

### 3. Read path — `current_degraded(db)` with lazy expiry

Reads the singleton and applies **lazy time-based recovery**: if `degraded` and
`degraded_since` is older than `DEGRADED_COOLDOWN_SECONDS` (default 90), treat as
recovered — clear the row and return false, letting live traffic re-detect if it
is still broken. A recorded success also clears it immediately. No background job.

### 4. Server-side render

A `before_request` (or the embed view) resolves degraded state and passes
`degraded=True` into the embed template so a fresh page load shows the overlay.
To bound DB load, cache the resolved flag in-process per worker for
`HEALTH_CACHE_SECONDS` (default 5) → ≤ 1 read / 5s / worker. The template reuses
the existing `.maintenance-overlay` markup/styling; server-forced maintenance
still takes precedence.

### 5. `/health/detail` endpoint

Returns `{status, service, db: "ok"|"fail" (live SELECT 1), degraded,
degraded_since, consecutive_failures}`. No Anthropic ping. Serves external
monitors and upgrades phase 1's client confirmation probe (switch
`confirmOutage`'s fetch from `/health` to `/health/detail`, confirming an outage
when `db != "ok"` or `degraded` is true).

### 6. Config

Add to `main_ui/config.py`: `server_failure_threshold` (env
`OUTAGE_FAILURE_THRESHOLD`, default 5), `degraded_cooldown_seconds` (env
`OUTAGE_COOLDOWN_SECONDS`, default 90), `health_cache_seconds` (env
`OUTAGE_HEALTH_CACHE_SECONDS`, default 5).

## Testing

- pytest for the recorder: threshold trip, success reset, lazy expiry,
  idempotent `degraded_since`, best-effort swallow of DB errors.
- pytest for `/health/detail`: healthy, degraded, db-fail shapes.
- Migration applies cleanly (upgrade/downgrade) and seeds the row.

## Out of scope

Active/synthetic probing, auto-503 of the API, Slack/email alerting,
multi-replica coordination beyond Postgres.
