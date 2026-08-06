"""Flask test-client checks for the no-default-course behavior in sandbox_ui.

Mirrors ``main_ui.routes.test_embed_no_course``: a bare host URL (``/``) or an
``/embed`` with no ``course`` param must NOT fall back to a default course.
Instead the page renders with an empty course context (HTTP 200) and the first
chat send fails course validation (HTTP 404), which the frontend surfaces as the
generic error banner.

Run:
    python -m sandbox_ui.routes.test_embed_no_course
"""
from __future__ import annotations

from sandbox_ui.run_app import app


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()

    root = client.get("/")
    ok &= _check("/ renders", root.status_code == 200, root.status_code)
    ok &= _check(
        "/ has empty course config",
        b'"course": ""' in root.data or b'"course":""' in root.data,
    )

    emb = client.get("/embed")
    ok &= _check("/embed (no course) renders", emb.status_code == 200, emb.status_code)
    ok &= _check(
        "/embed (no course) has empty course config",
        b'"course": ""' in emb.data or b'"course":""' in emb.data,
    )

    sent = client.post("/api/chat", json={"text": "test", "course": "", "exercise": "1"})
    ok &= _check("chat with empty course -> 404", sent.status_code == 404, sent.status_code)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
