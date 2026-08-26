"""GET /health/detail — main_ui diagnostic health endpoint.

Richer companion to the factory's static ``/health`` liveness probe: it does a
live ``SELECT 1`` and reports the automatic outage-detection state
(``service_health`` row). Serves external monitors and backs phase 1's client
confirmation probe — ``chat.js`` treats an outage as confirmed when
``db != "ok"`` or ``degraded`` is true.

main_ui-only (sandbox_ui has no ``service_health`` table), so it lives on its own
blueprint here rather than in the shared app factory. No Anthropic/LLM ping — the
signal is passive, derived from real traffic.
"""

from __future__ import annotations

from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from main_ui.db.session import SessionLocal
from main_ui.services import service_health


health_bp = Blueprint("health_detail", __name__)


@health_bp.get("/health/detail")
def detail():
    """Return liveness + DB reachability + automatic outage state as JSON."""
    db_ok = False
    snapshot = {"degraded": False, "degraded_since": None, "consecutive_failures": 0}
    session = None
    try:
        session = SessionLocal()
        session.execute(text("SELECT 1"))
        db_ok = True
        # Same lazy-expiry read the page render uses, so the endpoint agrees with
        # what a fresh load would show. Any error here leaves the safe defaults.
        snapshot = service_health.health_snapshot(session)
        session.commit()
    except Exception:  # pragma: no cover - defensive; endpoint must not 500
        if session is not None:
            try:
                session.rollback()
            except Exception:
                pass
        current_app.logger.warning("/health/detail degraded read failed", exc_info=True)
    finally:
        if session is not None:
            session.close()

    payload = {
        "status": "ok" if db_ok else "degraded",
        "service": "main_ui",
        "db": "ok" if db_ok else "fail",
        **snapshot,
    }
    # 200 even when degraded/db-fail so the probe body is always readable; the
    # fields carry the real state. (A hard 5xx here would make monitors flap.)
    return jsonify(payload)
