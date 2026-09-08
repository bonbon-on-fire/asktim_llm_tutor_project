"""End-to-end: the deliberate exam-period lockout through the real HTTP surface.

MAIN_UI_EXAM_LOCKDOWN=1 is set BEFORE importing the app (the gate is captured at
create_app time, and embed reads the flag per request), then we check that:

  * the embed pages (/ and /embed) render the exam overlay with exam wording and
    NOT the maintenance/outage wording, and are NOT marked data-auto-degraded
    (a forced overlay, so chat.js stands the auto monitor down)
  * a functional /api/* call is refused server-side with 503 error:"exam_lockdown"
    (so the lockout can't be clicked past by deleting the overlay)
  * the allowlisted endpoints stay reachable: /health 200 and the embed pages 200

Uses a throwaway sqlite DB, same harness style as test_outage_integration.py.

Run:
    python -m main_ui.routes.test_exam_lockdown
"""
from __future__ import annotations

import os
import tempfile

# Point the app at a throwaway DB and turn ON exam lockdown BEFORE importing the app.
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_DB_FD)
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["MAIN_UI_SECRET_KEY"] = "test"
os.environ["MAIN_UI_EXAM_LOCKDOWN"] = "1"
# Make sure the maintenance flag is off, so we prove exam lockdown alone gates.
os.environ["MAIN_UI_MAINTENANCE"] = "0"

from main_ui.run_app import app  # noqa: E402
from main_ui.db.models import Base  # noqa: E402
from main_ui.db import engine  # noqa: E402

COURSE = "supply_chain_design"
EXERCISE = "1"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    Base.metadata.create_all(engine)
    client = app.test_client()

    # ---- A. Embed pages render the exam overlay, not the outage wording. ----
    for path in ("/", f"/embed?course={COURSE}&exercise={EXERCISE}"):
        resp = client.get(path)
        html = resp.get_data(as_text=True)
        ok &= _check(f"{path}: 200", resp.status_code == 200, resp.status_code)
        ok &= _check(f"{path}: overlay rendered", "maintenance-overlay" in html, path)
        ok &= _check(
            f"{path}: exam wording shown",
            "AskTIM is currently unavailable" in html
            and "exam period" in html,
            path,
        )
        ok &= _check(
            f"{path}: outage wording NOT shown",
            "temporarily down" not in html,
            path,
        )
        ok &= _check(
            f"{path}: not marked auto-degraded",
            'data-auto-degraded="true"' not in html,
            path,
        )

    # ---- B. Functional API is refused server-side (503 exam_lockdown). ----
    resp = client.post(
        "/api/chat", json={"text": "hi", "course": COURSE, "exercise": EXERCISE}
    )
    body = resp.get_json()
    ok &= _check("POST /api/chat: 503", resp.status_code == 503, resp.status_code)
    ok &= _check(
        "POST /api/chat: exam_lockdown body",
        isinstance(body, dict) and body.get("error") == "exam_lockdown",
        body,
    )
    ok &= _check(
        "POST /api/chat: Retry-After set",
        resp.headers.get("Retry-After") == "120",
        resp.headers.get("Retry-After"),
    )

    resp = client.get("/api/history")
    ok &= _check("GET /api/history: also 503", resp.status_code == 503, resp.status_code)

    # ---- C. Allowlisted health probe stays reachable. ----
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
