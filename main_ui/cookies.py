"""Cookie name constants, attribute defaults, and session UUID generation.

Single source of truth for cookie policy. Routes call `new_session_id()` and
`default_cookie_kwargs()` rather than constructing attributes inline so the
policy stays consistent everywhere it gets applied.
"""

from __future__ import annotations

import uuid

from main_ui.config import load_config


SESSION_COOKIE_NAME = "tutor_session_id"
EMAIL_COOKIE_NAME = "tutor_email"  # Used by Step 7; defined here for policy centralization.


def new_session_id() -> str:
    """Generate a fresh anonymous session id (UUIDv4)."""
    return str(uuid.uuid4())


def default_cookie_kwargs() -> dict:
    """Cookie attribute kwargs passed to Flask's `response.set_cookie(...)`.

    Defaults chosen for iframe / third-party context:
    - HttpOnly: JS can't read; defends against XSS leaking the session id
    - SameSite=None + Secure: required for cross-site iframe contexts
    - Partitioned: CHIPS — partition the cookie per top-level site
    - Max-Age: ~180 days (configurable via MAIN_UI_COOKIE_MAX_AGE)

    For local dev on http://localhost (no HTTPS), set
    MAIN_UI_COOKIE_SECURE=false so browsers that strictly enforce `Secure`
    still accept the cookie.
    """
    config = load_config()
    return {
        "httponly": True,
        "samesite": "None",
        "secure": config.cookie_secure,
        "max_age": config.cookie_max_age_seconds,
        "path": "/",
        "partitioned": True,
    }
