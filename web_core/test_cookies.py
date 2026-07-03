"""Standalone tests for web_core.cookies (no pytest).

Run with:
    python -m web_core.test_cookies
"""

from __future__ import annotations

import uuid

from web_core.cookies import (
    SESSION_COOKIE_NAME,
    USERNAME_COOKIE_NAME,
    new_session_id,
    default_cookie_kwargs,
)

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


def test_constants_and_session_id() -> None:
    _check("session cookie name", SESSION_COOKIE_NAME == "tutor_session_id")
    _check("username cookie name", USERNAME_COOKIE_NAME == "tutor_username")
    sid = new_session_id()
    _check("new_session_id is a uuid4 string", str(uuid.UUID(sid)) == sid)


def test_default_cookie_kwargs() -> None:
    got = default_cookie_kwargs(secure=True, max_age=100)
    _check(
        "policy dict is exact",
        got == {"httponly": True, "samesite": "None", "secure": True, "max_age": 100, "path": "/", "partitioned": True},
        f"got {got}",
    )
    _check("secure passes through", default_cookie_kwargs(secure=False, max_age=1)["secure"] is False)


def main() -> int:
    for t in (test_constants_and_session_id, test_default_cookie_kwargs):
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
