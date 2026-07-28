"""Flask test-client: stateless chat caps (per-message tokens, upload login).

Run:
    python -m main_ui.routes.test_chat_caps
"""
from __future__ import annotations

import io

from main_ui.run_app import app
from main_ui.routes._validation import DEFAULT_COURSE, DEFAULT_EXERCISE


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()
    ex = DEFAULT_EXERCISE

    # Oversized text -> 400 message_too_long, before any course/DB work.
    r = client.post("/api/chat", json={
        "text": "z" * 60000, "course": DEFAULT_COURSE, "exercise": ex,
    })
    ok &= _check("huge text -> 400", r.status_code == 400, r.status_code)
    ok &= _check("huge text -> message_too_long", r.get_json().get("error") == "message_too_long", r.get_json())

    # A file upload with no username cookie -> 403 login_required.
    data = {
        "text": "here is my file",
        "course": DEFAULT_COURSE,
        "exercise": ex,
        "files": (io.BytesIO(b"col1,col2\n1,2\n"), "data.csv"),
    }
    r = client.post("/api/chat", data=data, content_type="multipart/form-data")
    ok &= _check("upload logged-out -> 403", r.status_code == 403, r.status_code)
    ok &= _check("upload logged-out -> login_required", r.get_json().get("error") == "login_required", r.get_json())

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
