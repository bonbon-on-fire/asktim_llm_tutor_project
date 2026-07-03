"""Single shared-password gate for database_ui.

The review tool exposes every student's conversations and uploaded images, so it
must not be open. This is a deliberately small gate: one shared password
(``DATABASE_UI_PASSWORD``) unlocks the whole tool for the browser session via a
signed Flask session cookie. Not per-user auth — sufficient for a small internal
review tool, and easy to swap for SSO later.

If ``DATABASE_UI_PASSWORD`` is unset (local dev only), the gate is open.
"""

from __future__ import annotations

from flask import Flask, current_app, redirect, request, session, url_for

_SESSION_KEY = "database_authed"

# Endpoints reachable without auth: the login form/submit and the health check.
# Both this app's own static endpoint (database.css) and the shared
# ui_core.static endpoint (chat.css) are also allowed so the login page can
# load all of its CSS.
_PUBLIC_ENDPOINTS = {
    "database.login",
    "database.login_submit",
    "health",
    "static",
    "ui_core.static",
}


def password_required() -> bool:
    """True if a password is configured (i.e. the gate is active)."""
    return bool(current_app.config.get("DATABASE_UI_PASSWORD"))


def is_authed() -> bool:
    """True if the current session may view the tool."""
    if not password_required():
        return True  # no password configured -> open (local dev)
    return bool(session.get(_SESSION_KEY))


def check_password(candidate: str) -> bool:
    """True if *candidate* matches the configured password."""
    expected = current_app.config.get("DATABASE_UI_PASSWORD")
    return bool(expected) and candidate == expected


def mark_authed() -> None:
    session[_SESSION_KEY] = True
    session.permanent = True


def clear_auth() -> None:
    session.pop(_SESSION_KEY, None)


def init_auth(app: Flask) -> None:
    """Register the before-request guard that protects every non-public route."""

    @app.before_request
    def _require_auth():
        if request.endpoint in _PUBLIC_ENDPOINTS:
            return None
        if is_authed():
            return None
        return redirect(url_for("database.login"))
