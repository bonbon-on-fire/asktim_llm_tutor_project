"""Server-side automatic outage detection for main_ui (phase 2).

Real ``/api/chat`` outcomes are the signal: every completed turn is a success,
every tutor-pipeline infra failure (stream exception, empty/failed reply, or a
persist error) is a failure. Those outcomes drive a single shared row
(``service_health``, id=1) so the "AskTIM is temporarily down" banner can engage
from live traffic across the ~4 gunicorn workers — no synthetic LLM probes, no
background thread, no Redis (Postgres is the only shared store).

Design notes:

* **Trip on a streak.** ``consecutive_failures`` climbs on failures and is reset
  to 0 by any success. Once it reaches ``outage_failure_threshold`` (default 5,
  higher than phase 1's per-browser 3 because this aggregates *all* students),
  ``degraded`` flips true. One success clears it.
* **Lazy recovery.** No background job clears the flag. ``current_degraded``
  treats a ``degraded`` row with no recorded failure for ``outage_cooldown_seconds``
  (default 90) as recovered, resets it, and lets live traffic re-detect if the
  outage returns. Keying on "quiet since the last failure" (``last_failure_at``)
  rather than "elapsed since the trip" (``degraded_since``) is deliberate: an
  ongoing outage keeps recording failures, so the flag holds through it instead
  of blinking off mid-outage. A recorded success also clears it.
* **Banner only.** This never 503s the API — the hard block stays the manual
  ``MAIN_UI_MAINTENANCE`` env flag. Keeping the API reachable is what lets a
  recovered service self-clear and bounds the blast radius of a false positive.

Callers use the *safe* wrappers (``record_chat_outcome_safe`` /
``is_degraded_cached``); the bare functions take an explicit session and are the
unit-tested core.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from main_ui.config import load_config
from main_ui.db.models import ServiceHealth

_SINGLETON_ID = 1

# Per-worker cache of the resolved degraded flag, so a burst of page loads costs
# at most one DB read per ``outage_health_cache_seconds`` per gunicorn worker.
# (worker-local; the authoritative state is the shared row.)
_cache_value: bool = False
_cache_expires_monotonic: float = 0.0


def _utcnow() -> datetime:
    """tz-aware UTC now (kept local so tests can pass an explicit ``now``)."""
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    """Coerce a possibly-naive stored datetime to tz-aware UTC for comparison.

    SQLite round-trips ``DateTime(timezone=True)`` as naive; Postgres keeps the
    offset. Normalizing here keeps the cooldown math correct on both.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def get_or_create(session: Session) -> ServiceHealth:
    """Return the singleton row, creating it if absent.

    The migration seeds it in production; this keeps the service correct under
    ``create_all`` (tests) and defends against a missing row.
    """
    row = session.get(ServiceHealth, _SINGLETON_ID)
    if row is None:
        row = ServiceHealth(id=_SINGLETON_ID, degraded=False, consecutive_failures=0)
        session.add(row)
        session.flush()
    return row


def record_chat_outcome(
    session: Session,
    ok: bool,
    *,
    threshold: int | None = None,
    now: datetime | None = None,
) -> ServiceHealth:
    """Fold one chat outcome into the shared health row and return it.

    ``ok=True`` resets the streak and clears any degraded state. ``ok=False``
    increments the streak and, at/above ``threshold``, engages degraded state.
    Caller is responsible for committing the session.
    """
    now = now or _utcnow()
    if threshold is None:
        threshold = load_config().outage_failure_threshold
    # Lock the row on Postgres so concurrent workers serialize the read-modify-
    # write; a no-op on SQLite, where writes are already serialized.
    row = session.get(ServiceHealth, _SINGLETON_ID, with_for_update=True)
    if row is None:
        row = get_or_create(session)

    if ok:
        row.consecutive_failures = 0
        row.last_success_at = now
        row.degraded = False
        row.degraded_since = None
    else:
        row.consecutive_failures = (row.consecutive_failures or 0) + 1
        row.last_failure_at = now
        if row.consecutive_failures >= threshold and not row.degraded:
            row.degraded = True
            row.degraded_since = now
    row.updated_at = now
    return row


def current_degraded(
    session: Session,
    *,
    cooldown_seconds: int | None = None,
    now: datetime | None = None,
) -> bool:
    """Return whether the service is currently degraded, applying lazy expiry.

    A degraded row is reset in-place and reported healthy once no failure has
    been recorded for ``cooldown_seconds`` (i.e. traffic has gone quiet or
    recovered), so live traffic re-detects a still-broken service. Keying expiry
    on ``last_failure_at`` rather than ``degraded_since`` keeps the flag engaged
    through an ongoing outage — which keeps recording failures — instead of
    blinking off after a fixed interval. Falls back to ``degraded_since`` when no
    failure timestamp exists. Caller commits.
    """
    now = now or _utcnow()
    if cooldown_seconds is None:
        cooldown_seconds = load_config().outage_cooldown_seconds
    row = session.get(ServiceHealth, _SINGLETON_ID)
    if row is None or not row.degraded:
        return False
    reference = _as_aware(row.last_failure_at) or _as_aware(row.degraded_since)
    if reference is not None and (now - reference) > timedelta(seconds=cooldown_seconds):
        row.degraded = False
        row.degraded_since = None
        row.consecutive_failures = 0
        row.updated_at = now
        return False
    return True


def is_degraded_cached(*, session_factory=None, cache_seconds: int | None = None) -> bool:
    """Return the degraded flag for a page render, cached per worker.

    Opens its own short-lived session (never the request session), applies lazy
    expiry, and caches the boolean for ``outage_health_cache_seconds`` so a
    traffic spike does not hammer the singleton row. Best-effort: any error
    resolves to "not degraded" so a health-tracking fault never blocks a render.
    """
    global _cache_value, _cache_expires_monotonic
    now_mono = time.monotonic()
    if now_mono < _cache_expires_monotonic:
        return _cache_value

    cfg = load_config()
    if cache_seconds is None:
        cache_seconds = cfg.outage_health_cache_seconds
    if session_factory is None:
        # Imported lazily to avoid import-time coupling to the engine.
        from main_ui.db.session import SessionLocal as session_factory

    session = None
    try:
        session = session_factory()
        value = current_degraded(session, cooldown_seconds=cfg.outage_cooldown_seconds)
        session.commit()
    except Exception:  # pragma: no cover - defensive; render must not break
        if session is not None:
            try:
                session.rollback()
            except Exception:
                pass
        value = False
    finally:
        if session is not None:
            session.close()

    _cache_value = value
    _cache_expires_monotonic = now_mono + max(0, cache_seconds)
    return value


def health_snapshot(session: Session) -> dict:
    """Return a JSON-able view of the health row for ``/health/detail``.

    Applies the same lazy expiry as ``current_degraded`` so the endpoint agrees
    with what the page render sees.
    """
    degraded = current_degraded(session)
    row = session.get(ServiceHealth, _SINGLETON_ID)
    since = _as_aware(row.degraded_since) if row else None
    return {
        "degraded": degraded,
        "degraded_since": since.isoformat() if since else None,
        "consecutive_failures": (row.consecutive_failures if row else 0),
    }
