"""Shared cookie policy for the web chat apps.

Single source of truth for cookie names and the attribute policy applied to
Flask ``response.set_cookie(...)``. Each app passes its own ``secure`` and
``max_age`` (which come from that app's config) into ``default_cookie_kwargs``.
"""

from __future__ import annotations

import uuid

SESSION_COOKIE_NAME = "tutor_session_id"
USERNAME_COOKIE_NAME = "tutor_username"


def new_session_id() -> str:
    """Generate a fresh anonymous session id (UUIDv4)."""
    return str(uuid.uuid4())


def default_cookie_kwargs(*, secure: bool, max_age: int) -> dict:
    """Cookie attribute kwargs for Flask ``response.set_cookie(...)``.

    HttpOnly + SameSite=None + Secure + Partitioned (CHIPS) for iframe /
    third-party context. ``secure`` and ``max_age`` come from the app's config.
    """
    return {
        "httponly": True,
        "samesite": "None",
        "secure": secure,
        "max_age": max_age,
        "path": "/",
        "partitioned": True,
    }
