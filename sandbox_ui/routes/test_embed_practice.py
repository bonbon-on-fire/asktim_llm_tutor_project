"""Flask test-client checks for practice URL handling in sandbox_ui /embed.

Run:
    python -m sandbox_ui.routes.test_embed_practice
"""
from __future__ import annotations

from sandbox_ui.run_app import app
from sandbox_ui.routes._validation import DEFAULT_COURSE, list_practice


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()
    both = client.get(f"/embed?course={DEFAULT_COURSE}&exercise=1&practice=1")
    ok &= _check("both params -> 404", both.status_code == 404, both.status_code)

    practices = list_practice(DEFAULT_COURSE)
    if practices:
        n = practices[0]
        r = client.get(f"/embed?course={DEFAULT_COURSE}&practice={n}")
        ok &= _check("valid practice renders", r.status_code == 200, r.status_code)
        ok &= _check("kind in page config", b'"exerciseKind": "practice"' in r.data or b'"exerciseKind":"practice"' in r.data)
    else:
        print("SKIP - DEFAULT_COURSE has no practice files")

    bad = client.get(f"/embed?course={DEFAULT_COURSE}&practice=9999")
    ok &= _check("invalid practice -> 404", bad.status_code == 404, bad.status_code)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
