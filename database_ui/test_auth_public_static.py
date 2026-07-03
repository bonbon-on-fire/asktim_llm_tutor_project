"""Standalone regression test for database_ui's auth allowlist (no pytest).

Regression: chat.css moved from database_ui's own /static route to the shared
ui_core.static blueprint (/ui-core/css/chat.css). The auth gate's
_PUBLIC_ENDPOINTS allowlist listed "static" (database.css) but not
"ui_core.static" (chat.css), so on a password-protected deploy an
unauthenticated visitor hitting /login could not load chat.css: the request
got redirected to /login instead of served, leaving the login page unstyled.

This test builds the real app with the auth gate ACTIVE (a password
configured) and no session cookie, then asserts:
- GET /ui-core/css/chat.css -> 200 (public; the regression this fixes)
- GET /static/css/database.css -> 200 (still public)
- GET / (a protected route) -> 302 redirect to the login page (proves the
  gate is genuinely active, so the 200s above are meaningful)

Run with:
    python -m database_ui.test_auth_public_static
"""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_UI_DATABASE_URL", "sqlite:///./main_ui.db")

from database_ui.run_app import create_app

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def _make_client():
    app = create_app()
    # Make the gate active regardless of the environment the test runs in.
    app.config["DATABASE_UI_PASSWORD"] = "test-password"
    return app.test_client()


def test_shared_chat_css_is_public() -> None:
    client = _make_client()
    resp = client.get("/ui-core/css/chat.css")
    _check(
        "GET /ui-core/css/chat.css -> 200",
        resp.status_code == 200,
        f"got {resp.status_code}",
    )


def test_own_database_css_is_public() -> None:
    client = _make_client()
    resp = client.get("/static/css/database.css")
    _check(
        "GET /static/css/database.css -> 200",
        resp.status_code == 200,
        f"got {resp.status_code}",
    )


def test_protected_route_redirects_to_login() -> None:
    client = _make_client()
    resp = client.get("/", follow_redirects=False)
    _check(
        "GET / -> 302",
        resp.status_code == 302,
        f"got {resp.status_code}",
    )
    location = resp.headers.get("Location", "")
    _check(
        "redirect targets login page",
        location.endswith("/login"),
        f"got Location={location!r}",
    )


def main() -> int:
    for t in (
        test_shared_chat_css_is_public,
        test_own_database_css_is_public,
        test_protected_route_redirects_to_login,
    ):
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
