"""Cookie names + policy for main_ui — thin wrapper over ui_core.cookies.

Re-exports the shared constants and helpers; ``default_cookie_kwargs()`` stays a
no-arg call that reads main_ui's config, so route call sites are unchanged.
"""

from __future__ import annotations

from ui_core.cookies import (  # re-exported for existing importers
    SESSION_COOKIE_NAME,
    USERNAME_COOKIE_NAME,
    new_session_id,
    read_username_cookie,
    sign_username,
    default_cookie_kwargs as _base_cookie_kwargs,
)
from main_ui.config import load_config

__all__ = [
    "SESSION_COOKIE_NAME",
    "USERNAME_COOKIE_NAME",
    "new_session_id",
    "sign_username",
    "read_username_cookie",
    "default_cookie_kwargs",
]


def default_cookie_kwargs() -> dict:
    """Cookie kwargs using main_ui's configured secure flag and max-age."""
    config = load_config()
    return _base_cookie_kwargs(secure=config.cookie_secure, max_age=config.cookie_max_age_seconds)
