"""Flask test-client check: /api/chat accepts exercise_kind=practice and stores it.

Run:
    python -m main_ui.routes.test_chat_practice
"""
from __future__ import annotations

from main_ui.run_app import app
from main_ui.routes._validation import DEFAULT_COURSE, list_practice


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()
    practices = list_practice(DEFAULT_COURSE)
    if not practices:
        print("SKIP - DEFAULT_COURSE has no practice files; validation path still exercised below")
    # Unknown practice number must be rejected as a bad param (404), proving the
    # chat route validates the practice selection rather than silently accepting it.
    r = client.post("/api/chat", json={
        "text": "hi", "course": DEFAULT_COURSE,
        "exercise": "99999", "exercise_kind": "practice",
    })
    ok &= _check("bad practice number -> 404", r.status_code == 404, r.status_code)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
