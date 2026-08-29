# Auto-detection correctness — audit findings + fixes

**Date:** 2026-08-29
**Status:** Approved, implementing
**Relates to:** [2026-08-25-auto-outage-detection-server-design.md](2026-08-25-auto-outage-detection-server-design.md)

Supersedes the abandoned `2026-08-26-error-event-log-design.md` (durable error
log + database_ui dashboard + Telegram alert). That direction was dropped: the
priority is making the existing auto-detection *correct*, not adding new
surfaces. This doc records the audit of the detection path and the three
concrete fixes we're making, plus the limits we're documenting rather than
fixing.

## Audit summary

The passive detector (`service_health`, driven by real `/api/chat` outcomes)
works for failures that *return* an outcome, but has real holes:

- **A — server coverage hole.** Outcomes are recorded at only 4 points, all
  *inside* the tutor-stream generator ([chat.py:410/421/449/458](../../../main_ui/routes/chat.py)).
  Every infra failure *before* streaming starts (student/image/file persist,
  the pre-stream commit, and any throw in `find_or_create_conversation` /
  history+count reads) returns 500 but never increments the streak. A DB/storage
  outage would 500 every request yet never trip the server banner.
- **B — hang gap.** The Anthropic call has no per-request timeout (SDK default
  600s); gunicorn kills the worker at `--timeout 120` before any recorder runs,
  and the killed process runs no `finally`. A frozen tutor is invisible
  server-side.
- **C — semantic limits (documented, not fixed).** Partial/per-course outages
  are invisible (one global streak, reset by any success); a total Postgres
  outage is undetectable (the detector's own store is down); zero traffic = no
  signal; the per-worker 5s render cache briefly skews which students see the
  banner.
- **D — recovery flap.** Lazy expiry clears `degraded` once `degraded_since` is
  older than the cooldown *and zeroes the streak*
  ([service_health.py:135-140](../../../main_ui/services/service_health.py)). A
  real outage lasting past the cooldown blinks the banner OFF and then needs a
  fresh full streak to re-trip.

## Fixes

### Fix 1 — record pre-stream infra failures (closes A)

In `main_ui/routes/chat.py`, call `_record_chat_outcome_safe(False)` on every
pre-stream infra-failure exit, and add infra `except` handlers so a DB outage in
the read/find path is recorded (not an unhandled 500):

- `find_or_create_conversation` — keep `except WrongSessionError` (user error,
  not recorded); add `except Exception` → record + 500.
- the count/limit/history/student-persist block — wrap so an infra throw records
  + 500 (the `login_required` / `conversation_limit` early *returns* are
  untouched — they're returns, not exceptions).
- `image_persist_failed`, `file_persist_failed`, pre-stream `persist_failed`
  (commit) — add `_record_chat_outcome_safe(False)` before each existing 500.

User errors (validation 404s, login, conversation-limit, wrong-session) stay
**un**recorded. Note the inherent floor: a *total* DB outage also fails the
recorder's own session (swallowed) — this fix catches partial/storage failures
and any non-DB pre-stream infra throw, materially widening coverage.

### Fix 2 — per-request tutor timeout (closes B)

In `tutor/run_tutor.py`, add `_tutor_request_timeout()` reading
`TUTOR_REQUEST_TIMEOUT_SECONDS` (default **30.0**s) and pass it to both client
builders:

- `anthropic.Anthropic(api_key=..., timeout=...)` (raw/cached path)
- `ChatAnthropic(..., timeout=...)` (langchain path)

A stall with no streamed bytes then raises `APITimeoutError`, which is already
retryable pre-stream up to `_MAX_STREAM_RETRIES=2`. Worst case before it
propagates to [chat.py:408](../../../main_ui/routes/chat.py) (→ recorded, SSE
error frame) is `~3 × timeout + backoffs ≈ 91.5s`, safely under gunicorn's 120s.
30s is a generous time-to-first-token budget; once tokens stream, inter-token
gaps are tiny. Env-tunable if it needs adjusting.

### Fix 3 — recovery keyed on "no failures since", not "time since trip" (closes D)

In `service_health.current_degraded`, base lazy expiry on `last_failure_at`
instead of `degraded_since`: a degraded row is treated as recovered only when
**no failure has been recorded for `cooldown_seconds`**. An ongoing outage keeps
recording failures (`last_failure_at` advances every failed send, even while
already degraded), so it stays degraded until a real success clears it or
traffic genuinely goes quiet. Falls back to `degraded_since` if
`last_failure_at` is null. This removes the mid-outage blink-off.

## Testing

- `main_ui/services/test_service_health.py` — extend for Fix 3: degraded + recent
  `last_failure_at` stays degraded past the old `degraded_since`+cooldown window;
  degraded + stale `last_failure_at` (quiet) clears; success still clears
  immediately.
- `main_ui/routes/test_outage_integration.py` — extend for Fix 1: a pre-stream
  `find_or_create_conversation` throw records a failure and returns 500; an
  image/persist-commit failure records; a user error (login/limit) does NOT.
- `tutor/test_stream_retry.py` (or a sibling) — Fix 2: both client builders
  receive the configured timeout; a persistent `APITimeoutError` with no bytes
  retries the bounded number of times then propagates (never loops).

## Out of scope (documented limits — C)

Partial/per-course outages, total-Postgres outage, quiet-traffic blindness, and
per-worker cache skew are inherent to the passive, no-Redis, traffic-driven
design. Documented in the `service_health` module docstring; addressing them
would require active probing or a shared cache and is not planned.
