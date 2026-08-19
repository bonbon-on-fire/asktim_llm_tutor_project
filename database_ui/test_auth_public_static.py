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
- GET / -> 200 rendering the shell WITH the login overlay (signed-out visitors
  see the site, blurred, behind the login modal)
- GET /api/conversations -> 401 (the data endpoints stay blocked, so the
  visible shell exposes no conversations — this is the real enforcement)

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
    """Record and print a pass/fail result for one named assertion."""
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def _make_client():
    """Build a test client for the app with the auth gate forced active."""
    app = create_app()
    # Make the gate active regardless of the environment the test runs in.
    app.config["DATABASE_UI_PASSWORD"] = "test-password"
    return app.test_client()


def test_shared_chat_css_is_public() -> None:
    """Assert the shared ui_core chat.css is served (200) without auth."""
    client = _make_client()
    resp = client.get("/ui-core/css/chat.css")
    _check(
        "GET /ui-core/css/chat.css -> 200",
        resp.status_code == 200,
        f"got {resp.status_code}",
    )


def test_own_database_css_is_public() -> None:
    """Assert the app's own database.css is served (200) without auth."""
    client = _make_client()
    resp = client.get("/static/css/database.css")
    _check(
        "GET /static/css/database.css -> 200",
        resp.status_code == 200,
        f"got {resp.status_code}",
    )


def test_unauthed_index_renders_shell_with_login_overlay() -> None:
    """Assert signed-out ``/`` renders the shell (200) with the login overlay.

    The shell is served (not redirected) so the login modal can sit over the
    real site, but it must carry the login overlay and no conversation data.
    """
    client = _make_client()
    resp = client.get("/", follow_redirects=False)
    _check("GET / -> 200 (shell renders)", resp.status_code == 200, f"got {resp.status_code}")
    body = resp.get_data(as_text=True)
    _check("login overlay present", "review-login-overlay" in body, "overlay markup missing")


def test_unauthed_data_api_is_blocked() -> None:
    """Assert a data endpoint stays blocked (401) when unauthed.

    This is the real enforcement: the shell is visible, but no chats leak
    because the /api endpoints that fill it are refused server-side.
    """
    client = _make_client()
    resp = client.get("/api/conversations", follow_redirects=False)
    _check(
        "GET /api/conversations -> 401 (data blocked)",
        resp.status_code == 401,
        f"got {resp.status_code}",
    )


def main() -> int:
    """Run all checks, print a summary, and return a shell exit code."""
    for t in (
        test_shared_chat_css_is_public,
        test_own_database_css_is_public,
        test_unauthed_index_renders_shell_with_login_overlay,
        test_unauthed_data_api_is_blocked,
    ):
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
