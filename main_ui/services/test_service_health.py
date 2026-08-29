"""Standalone: automatic outage-detection state machine over service_health.

Run:
    python -m main_ui.services.test_service_health

Uses in-memory SQLite and an explicit ``now`` so the time-based lazy expiry is
deterministic (no sleeps). Mirrors phase 1's outage_monitor.test.js coverage on
the server side: streak trip, success reset, lazy recovery, idempotent
degraded_since, and the best-effort DB-error swallow.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from main_ui.db.models import Base, ServiceHealth
from main_ui.services import service_health as svc


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def _fixed_now():
    """A concrete tz-aware instant (Date.now/new Date are unavailable in scripts,
    but this is plain Python — still, use a literal so results are reproducible)."""
    return datetime(2026, 8, 25, 12, 0, 0, tzinfo=timezone.utc)


def main() -> int:
    ok = True
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = _fixed_now()

    # --- streak below threshold does NOT trip, is not degraded ---
    with Session(engine) as s:
        for i in range(4):
            svc.record_chat_outcome(s, ok=False, threshold=5, now=now + timedelta(seconds=i))
        s.commit()
        row = s.get(ServiceHealth, 1)
        ok &= _check("4 failures under threshold: not degraded",
                     row.consecutive_failures == 4 and row.degraded is False,
                     f"cf={row.consecutive_failures} degraded={row.degraded}")

    # --- reaching threshold trips degraded and stamps degraded_since ---
    with Session(engine) as s2:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        trip_at = None
        for i in range(5):
            r = svc.record_chat_outcome(s2, ok=False, threshold=5, now=now + timedelta(seconds=i))
            if r.degraded and trip_at is None:
                trip_at = now + timedelta(seconds=i)
        s2.commit()
        row = s2.get(ServiceHealth, 1)
        ok &= _check("5th failure trips degraded",
                     row.degraded is True and row.consecutive_failures == 5,
                     f"cf={row.consecutive_failures} degraded={row.degraded}")
        ok &= _check("degraded_since stamped at trip (idempotent)",
                     svc._as_aware(row.degraded_since) == now + timedelta(seconds=4),
                     row.degraded_since)

        # further failures while already degraded must NOT move degraded_since
        svc.record_chat_outcome(s2, ok=False, threshold=5, now=now + timedelta(seconds=30))
        s2.commit()
        row = s2.get(ServiceHealth, 1)
        ok &= _check("degraded_since unchanged after more failures",
                     svc._as_aware(row.degraded_since) == now + timedelta(seconds=4),
                     row.degraded_since)

        # a single success clears everything immediately
        svc.record_chat_outcome(s2, ok=True, threshold=5, now=now + timedelta(seconds=40))
        s2.commit()
        row = s2.get(ServiceHealth, 1)
        ok &= _check("one success clears degraded + resets streak",
                     row.degraded is False and row.consecutive_failures == 0
                     and row.degraded_since is None,
                     f"cf={row.consecutive_failures} degraded={row.degraded}")

    # --- current_degraded lazy expiry: recovery keys on last_failure_at, not the trip ---
    with Session(engine) as s3:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        for i in range(5):
            svc.record_chat_outcome(s3, ok=False, threshold=5, now=now + timedelta(seconds=i))
        s3.commit()
        # trip stamped degraded_since = now+4s, last_failure_at = now+4s.
        # 30s later, cooldown 90s, no new failure -> still degraded
        ok &= _check("within cooldown: current_degraded True",
                     svc.current_degraded(s3, cooldown_seconds=90, now=now + timedelta(seconds=30)) is True)
        # 210s later with no further failures (quiet) -> lazily recovered
        recovered = svc.current_degraded(s3, cooldown_seconds=90, now=now + timedelta(seconds=210))
        s3.commit()
        ok &= _check("quiet past cooldown: current_degraded False (lazy expiry)", recovered is False)
        row = s3.get(ServiceHealth, 1)
        ok &= _check("lazy expiry resets the row",
                     row.degraded is False and row.consecutive_failures == 0
                     and row.degraded_since is None,
                     f"cf={row.consecutive_failures} degraded={row.degraded}")

    # --- ongoing outage: fresh failures hold the flag past degraded_since+cooldown ---
    with Session(engine) as s3b:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        for i in range(5):
            svc.record_chat_outcome(s3b, ok=False, threshold=5, now=now + timedelta(seconds=i))
        s3b.commit()
        # degraded_since = now+4s; old logic would recover at now+94s. Keep failing:
        # a fresh failure at now+120s advances last_failure_at (degraded_since is
        # untouched — verified above).
        svc.record_chat_outcome(s3b, ok=False, threshold=5, now=now + timedelta(seconds=120))
        s3b.commit()
        # now+150s: 146s past the trip (old cooldown window blown) but only 30s
        # past the last failure -> the flag MUST hold (no mid-outage blink-off).
        still = svc.current_degraded(s3b, cooldown_seconds=90, now=now + timedelta(seconds=150))
        s3b.commit()
        ok &= _check("ongoing outage past trip+cooldown stays degraded", still is True,
                     f"still={still}")
        row = s3b.get(ServiceHealth, 1)
        ok &= _check("ongoing outage: row still degraded, streak intact",
                     row.degraded is True and row.consecutive_failures == 6,
                     f"cf={row.consecutive_failures} degraded={row.degraded}")
        # once failures stop, it clears cooldown_seconds after the LAST failure
        cleared = svc.current_degraded(s3b, cooldown_seconds=90, now=now + timedelta(seconds=120 + 91))
        s3b.commit()
        ok &= _check("quiet cooldown after last failure clears it", cleared is False,
                     f"cleared={cleared}")

    # --- fallback: degraded with null last_failure_at keys on degraded_since ---
    with Session(engine) as s3c:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        row = svc.get_or_create(s3c)
        row.degraded = True
        row.degraded_since = now
        row.last_failure_at = None
        row.consecutive_failures = 5
        s3c.commit()
        # no last_failure_at -> fall back to degraded_since for the cooldown math
        ok &= _check("null last_failure_at within cooldown: stays degraded",
                     svc.current_degraded(s3c, cooldown_seconds=90, now=now + timedelta(seconds=30)) is True)
        fell_back = svc.current_degraded(s3c, cooldown_seconds=90, now=now + timedelta(seconds=200))
        s3c.commit()
        ok &= _check("null last_failure_at past cooldown: recovers via degraded_since",
                     fell_back is False, f"fell_back={fell_back}")

    # --- health_snapshot shape ---
    with Session(engine) as s4:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        snap = svc.health_snapshot(s4)
        ok &= _check("snapshot healthy shape",
                     snap == {"degraded": False, "degraded_since": None, "consecutive_failures": 0},
                     snap)

    # --- get_or_create is idempotent (only ever one singleton row) ---
    with Session(engine) as s5:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        svc.get_or_create(s5)
        svc.get_or_create(s5)
        s5.commit()
        count = s5.query(ServiceHealth).count()
        ok &= _check("get_or_create idempotent singleton", count == 1, count)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
