# Provider-outage markers on the weekly report

Date: 2026-09-03
Scope: `main_ui` (capture) + `database_ui/analytics` (read + render).
Complements auto outage detection (`2026-08-25-auto-outage-detection-server-design.md`,
table `service_health`) and the weekly report (`2026-08-12-weekly-report-design.md`).

## Problem

The weekly report's "Daily activity" chart shows a Sun–Sat bar per day of
conversation/message volume. When the tutor was degraded on a given day, that
day's bars are depressed for a reason that has nothing to do with student
behaviour — but the report gives no hint of it, so a reader (instructor or us)
can misread an outage dip as a quiet day. We want affected days flagged on the
chart so the numbers are read in context.

The blocker: outages are **not currently persisted as history**. `service_health`
is a single mutable row (id=1) describing *"are we degraded right now?"*; once an
outage clears, the day it happened leaves no durable, queryable trace (only
CRITICAL log lines and webhook posts, neither reachable from the report). So this
feature is two halves: **capture** outages as dated episodes, then **surface**
them on the report.

## Constraints (from the codebase)

- **4 gunicorn workers, single replica, no Redis.** Shared state is Postgres
  (`DATABASE_URL`). The capture path runs inside `record_chat_outcome` /
  `current_degraded`, which already lock and fold into the singleton row.
- **Alembic migrations** run on every deploy; no boot-time `create_all` in prod.
  A new table chains off current head `c4e8a1b6d902` (`add_service_health`).
- **Two apps, one database.** `database_ui` resolves its DB from
  `DATABASE_UI_DATABASE_URL` → `DATABASE_URL` and already reads main_ui-owned
  tables (`conversations`, `messages`, …) through its own read-only models. It
  runs **no migrations** — `main_ui` owns the schema.
- **The report is a cached JSON payload** built by `analytics/weekly.py:run_week`
  and rendered by `static/js/analytics.js`. Existing per-day data
  (`conversations_by_day`, `messages_by_day`) comes from `analytics/stats.py`,
  keyed by `started_at.astimezone(TZ).date()`.
- The capture code must be **best-effort and non-raising**, matching the existing
  outage code: a failure to log an incident must never break a chat turn.

## Decisions (approved)

- **Option A — a dedicated append-only `provider_outage` table.** Chosen over
  mining logs (fragile) or a per-day boolean stamped at cache time (misses short
  outages between cache runs). Gives precise start/end, queryable by day.
- **Track the `service_health` degraded *episode*,** not individual failures or
  the separately-debounced hard-down provider alert. The degraded flag is the
  same "AskTIM is down" signal that drives the banner and is what actually
  depresses a day's volume, and it has clean open/close transitions.
- **Marker on the existing Daily-activity chart** (the icon idea), tooltip for
  detail. No separate "Reliability" summary line in v1 (easy to add later).

## Design

### 1. `provider_outage` table (main_ui-owned)

Append-only; one row per degraded episode.

| column       | type          | null | notes                                   |
|--------------|---------------|------|-----------------------------------------|
| `id`         | integer PK    | no   | autoincrement                           |
| `started_at` | timestamptz   | no   | when degraded flipped true              |
| `ended_at`   | timestamptz   | yes  | NULL while ongoing; set when it clears  |
| `reason`     | text          | yes  | hard-down code if known, else NULL      |
| `updated_at` | timestamptz   | no   | server_default now()                    |

New model `ProviderOutage` in `main_ui/db/models.py`. New Alembic revision under
`main_ui/db/migrations/versions/`, `down_revision = 'c4e8a1b6d902'`, creating the
table (no seed row — it starts empty). At most one row has `ended_at IS NULL` at
a time (single service, single degraded flag), so "the open incident" is always
unambiguous.

### 2. Capture — three existing transitions in `main_ui/services/service_health.py`

A new module-internal helper set (best-effort, wrapped so it cannot raise; the
callers already commit the session):

- **Open** — in `record_chat_outcome`, at the point degraded flips
  `False → True` (`consecutive_failures >= threshold and not row.degraded`):
  insert `provider_outage(started_at=now, ended_at=NULL, reason=None)`. If an open
  row somehow already exists, do nothing (idempotent).
- **Close on success** — in `record_chat_outcome`, on an `ok=True` outcome **only
  when the row was previously degraded** (capture `was_degraded = row.degraded`
  before mutating): set the open incident's `ended_at = now`.
- **Close on lazy expiry** — in `current_degraded`, where a stale degraded row is
  reset: set the open incident's `ended_at = last_failure_at` (the true end —
  silence is not failure, mirroring why expiry keys on `last_failure_at`). Fall
  back to `now` if `last_failure_at` is absent.

`reason`: best-effort. `record_chat_outcome(ok=False)` is called generically for
many failure kinds and does not currently receive the exception, so v1 leaves
`reason` NULL. (A later pass can thread the `classify_provider_outage` code from
`provider_alerts.py` into the open path; out of scope here to keep the capture
change small and the two detectors decoupled.)

Closing helper: `UPDATE provider_outage SET ended_at=:end WHERE ended_at IS NULL`
(bounded to the single open row). All three helpers are individually
try/except-guarded and log-and-swallow, never propagating.

### 3. Read path — `database_ui/analytics`

- Read-only model `ProviderOutage` in `database_ui/db/models.py` mapping the same
  `provider_outage` table (same pattern as the existing read-only models).
- In `analytics/stats.py`, add a query for incidents **overlapping the report
  week**: `started_at < week_end AND (ended_at IS NULL OR ended_at >= week_start)`,
  with week bounds computed in the report TZ (same `astimezone(TZ)` convention as
  the day counters). Emit into the stats payload as a compact list:
  ```
  "outages": [
    {"start": "<iso>", "end": "<iso|null>", "reason": "<str|null>"},
    ...
  ]
  ```
  ISO timestamps in the report TZ; `end: null` means still ongoing.

The payload addition is backward-compatible: absent/empty `outages` renders
nothing, so already-cached weeks and clean weeks are unaffected.

### 4. Render — `database_ui/static/js/analytics.js`

- A helper maps each Sun–Sat day cell to whether any incident overlaps that
  calendar day (in the report TZ). Midnight-spanning and multi-day incidents mark
  every day they touch.
- For an affected day, draw a small warning marker (⚠ / dot) above that bar in
  `barChart` (or an overlay aligned to the bar), with a `<title>`/tooltip:
  `"Provider outage · Tue 14:05–16:15 (2h10m) · <reason>"`; an open incident shows
  `"…–ongoing"`; `reason` omitted when NULL.
- No incidents → nothing drawn; the chart is pixel-identical to today.
- Bump the `analytics.js` / `analytics.css` `?v=` in `templates/index.html`.

### 5. Testing

**main_ui (`services/test_service_health.py`):**
- Crossing the failure threshold opens exactly one `provider_outage` row
  (`ended_at IS NULL`); staying degraded does not open a second.
- A success after degraded closes the open row with `ended_at = success time`;
  a success while healthy opens/closes nothing.
- Lazy expiry closes the open row with `ended_at = last_failure_at`.
- Capture helpers swallow a forced DB error without propagating (chat-safe).

**database_ui (`analytics/tests/`):**
- The week query includes an incident wholly inside the week, one spanning
  midnight into the week, and an ongoing (`ended_at IS NULL`) incident; excludes
  incidents entirely outside the week.
- `stats` payload carries the `outages` list in the expected shape and TZ; empty
  when none.

## Out of scope (v1)

- Populating `reason` from the hard-down classifier (leave NULL; follow-up).
- A textual "Reliability" summary line / count under the chart.
- Backfilling historical outages (none are persisted; history starts at deploy).
- Any change to the live banner or `provider_alerts` webhook behaviour.

## Rollout

- Branch off `main` (not the current `feat/provider-outage-alerts` branch).
- Migration deploys with main_ui; the table starts empty and fills as new
  outages occur. The report shows markers only for weeks after deploy.
