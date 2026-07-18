"""Flask test-client checks for practice URL handling in main_ui /embed.

Run:
    python -m main_ui.routes.test_embed_practice
"""
from __future__ import annotations

from main_ui.run_app import app
from main_ui.routes._validation import DEFAULT_COURSE
from main_ui.routes import _validation as V


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()

    # Pick a real practice number available for DEFAULT_COURSE, else skip that leg.
    practices = V.list_practice(DEFAULT_COURSE) if hasattr(V, "list_practice") else V._discover_practice(DEFAULT_COURSE)
    both = client.get(f"/embed?course={DEFAULT_COURSE}&exercise=1&practice=1")
    ok &= _check("both params -> 404", both.status_code == 404, both.status_code)

    if practices:
        n = practices[0]
        r = client.get(f"/embed?course={DEFAULT_COURSE}&practice={n}")
        ok &= _check("valid practice renders", r.status_code == 200, r.status_code)
        ok &= _check("kind in page config", b'"exercise_kind": "practice"' in r.data or b'"exercise_kind":"practice"' in r.data)
    else:
        print("SKIP - DEFAULT_COURSE has no practice files")

    bad = client.get(f"/embed?course={DEFAULT_COURSE}&practice=9999")
    ok &= _check("invalid practice -> 404", bad.status_code == 404, bad.status_code)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
