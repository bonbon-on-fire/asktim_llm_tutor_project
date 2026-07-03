"""Cookie names + policy for sandbox_ui — thin wrapper over ui_core.cookies."""

from __future__ import annotations

from ui_core.cookies import (  # re-exported for existing importers
    SESSION_COOKIE_NAME,
    USERNAME_COOKIE_NAME,
    new_session_id,
    default_cookie_kwargs as _base_cookie_kwargs,
)
from sandbox_ui.config import load_config

__all__ = ["SESSION_COOKIE_NAME", "USERNAME_COOKIE_NAME", "new_session_id", "default_cookie_kwargs"]


def default_cookie_kwargs() -> dict:
    """Cookie kwargs using sandbox_ui's configured secure flag and max-age."""
    config = load_config()
    return _base_cookie_kwargs(secure=config.cookie_secure, max_age=config.cookie_max_age_seconds)
