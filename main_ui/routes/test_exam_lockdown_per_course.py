"""End-to-end: PER-COURSE exam lockdown through the real HTTP surface.

MAIN_UI_EXAM_LOCKDOWN=supply_chain_design is set BEFORE importing the app (the
gate is captured at create_app time, embed reads the flag per request), so only
that course is locked. We check that:

  * the LOCKED course's embed shows the exam overlay and its /api/chat 503s
  * an UNLISTED course's embed renders with NO overlay and its /api/chat is not
    gated (any status other than the 503 exam_lockdown)
  * a course-less functional call (/api/history) is NOT gated — per-course
    lockdown only blocks the named courses
  * the allowlisted /health probe stays reachable

Companion to test_exam_lockdown.py, which covers the bare `=1` all-courses case.

Run:
    python -m main_ui.routes.test_exam_lockdown_per_course
"""
from __future__ import annotations

import os
import tempfile

# Throwaway DB + lock ONLY supply_chain_design, BEFORE importing the app.
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_DB_FD)
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["MAIN_UI_SECRET_KEY"] = "test"
os.environ["MAIN_UI_EXAM_LOCKDOWN"] = "supply_chain_design"
os.environ["MAIN_UI_MAINTENANCE"] = "0"

from main_ui.run_app import app  # noqa: E402
from main_ui.db.models import Base  # noqa: E402
from main_ui.db import engine  # noqa: E402

LOCKED = "supply_chain_design"
OTHER = "urban_transportation"
EXERCISE = "1"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    Base.metadata.create_all(engine)
    client = app.test_client()

    # ---- A. Locked course: embed shows the exam overlay. ----
    resp = client.get(f"/embed?course={LOCKED}&exercise={EXERCISE}")
    html = resp.get_data(as_text=True)
    ok &= _check(f"locked embed: 200", resp.status_code == 200, resp.status_code)
    ok &= _check("locked embed: overlay rendered", "maintenance-overlay" in html)
    ok &= _check(
        "locked embed: exam wording shown",
        "AskTIM is currently unavailable" in html and "exam period" in html,
    )

    # ---- B. Locked course: functional API refused (503 exam_lockdown). ----
    resp = client.post(
        "/api/chat", json={"text": "hi", "course": LOCKED, "exercise": EXERCISE}
    )
    body = resp.get_json()
    ok &= _check("locked /api/chat: 503", resp.status_code == 503, resp.status_code)
    ok &= _check(
        "locked /api/chat: exam_lockdown body",
        isinstance(body, dict) and body.get("error") == "exam_lockdown",
        body,
    )

    # ---- C. Unlisted course: embed renders with NO overlay. ----
    resp = client.get(f"/embed?course={OTHER}&exercise={EXERCISE}")
    html = resp.get_data(as_text=True)
    ok &= _check(f"other embed: 200", resp.status_code == 200, resp.status_code)
    ok &= _check(
        "other embed: NO overlay", "maintenance-overlay" not in html, "overlay present"
    )

    # ---- D. Unlisted course: /api/chat is NOT exam-gated. ----
    # It may still fail validation/streaming, but must not be the 503 lockout.
    resp = client.post(
        "/api/chat", json={"text": "hi", "course": OTHER, "exercise": EXERCISE}
    )
    body = resp.get_json()
    exam_gated = resp.status_code == 503 and isinstance(body, dict) and body.get(
        "error"
    ) == "exam_lockdown"
    ok &= _check(
        "other /api/chat: not exam-gated", not exam_gated, (resp.status_code, body)
    )

    # ---- E. Course-less call is NOT gated under per-course lockdown. ----
    resp = client.get("/api/history")
    ok &= _check(
        "GET /api/history: not gated", resp.status_code != 503, resp.status_code
    )

    # ---- F. Allowlisted health probe stays reachable. ----
    resp = client.get("/health")
    ok &= _check("GET /health: 200", resp.status_code == 200, resp.status_code)

    engine.dispose()
    try:
        os.remove(_DB_PATH)
    except OSError:
        pass  # Windows may still hold the file open via a pooled connection.
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
