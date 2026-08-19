"""Password gate for database_ui, with optional per-course scoping.

The review tool exposes every student's conversations and uploaded files, so it
must not be open. A submitted password resolves to a *Scope*:

- the master ``DATABASE_UI_PASSWORD`` -> all-access (sees every course), or
- a per-course password (``DATABASE_UI_COURSE_PASSWORDS``) -> only its courses.

The resolved scope is stored in the signed Flask session cookie. If neither is
configured (local dev only), the gate is open and every request is all-access.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from flask import Flask, current_app, jsonify, redirect, request, session, url_for

_SESSION_KEY = "database_authed"
_SESSION_ALL_ACCESS = "all_access"
_SESSION_COURSES = "allowed_courses"

_PUBLIC_ENDPOINTS = {
    "database.login",
    "database.login_submit",
    "health",
    "static",
    "ui_core.static",
}


@dataclass(frozen=True)
class Scope:
    """What a logged-in session may see.

    ``all_access`` -> every course (master password or open dev). Otherwise
    ``courses`` lists the curriculum keys this session is restricted to.
    """

    all_access: bool
    courses: tuple[str, ...]


def password_required() -> bool:
    """True if any password is configured (i.e. the gate is active)."""
    cfg = current_app.config
    return bool(cfg.get("DATABASE_UI_PASSWORD") or cfg.get("DATABASE_UI_COURSE_PASSWORDS"))


def is_authed() -> bool:
    """True if the current session may view the tool."""
    if not password_required():
        return True  # no password configured -> open (local dev)
    return bool(session.get(_SESSION_KEY))


def resolve_scope(candidate: str) -> Scope | None:
    """Resolve a submitted password to a :class:`Scope`, or ``None`` if no match.

    The master password wins and grants all-access; otherwise the candidate is
    matched against the per-course map. Comparisons are constant-time.
    """
    master = current_app.config.get("DATABASE_UI_PASSWORD")
    if master and hmac.compare_digest(candidate, master):
        return Scope(all_access=True, courses=())
    course_passwords: dict[str, tuple[str, ...]] = (
        current_app.config.get("DATABASE_UI_COURSE_PASSWORDS") or {}
    )
    for password, courses in course_passwords.items():
        if hmac.compare_digest(candidate, password):
            return Scope(all_access=False, courses=tuple(courses))
    return None


def allowed_courses() -> list[str] | None:
    """Course keys the current session is restricted to, or ``None`` for no filter.

    ``None`` means all-access (master password, or open local-dev mode). A list
    means restrict queries to exactly those course keys.
    """
    if not password_required():
        return None
    if session.get(_SESSION_ALL_ACCESS):
        return None
    return list(session.get(_SESSION_COURSES, []))


def mark_authed(scope: Scope) -> None:
    """Mark the session authenticated for *scope* and make the cookie permanent."""
    session[_SESSION_KEY] = True
    session[_SESSION_ALL_ACCESS] = scope.all_access
    session[_SESSION_COURSES] = list(scope.courses)
    session.permanent = True


def clear_auth() -> None:
    """Clear all auth/scope state from the current session (log out)."""
    session.pop(_SESSION_KEY, None)
    session.pop(_SESSION_ALL_ACCESS, None)
    session.pop(_SESSION_COURSES, None)


def init_auth(app: Flask) -> None:
    """Register the before-request guard that protects every non-public route."""

    @app.before_request
    def _require_auth():
        """Gate every non-public route unless the session is authed.

        Signed-out visitors still get the ``index`` shell so the login modal can
        sit over the real review site (blurred). That shell carries no
        conversation data (it's filled client-side from the ``/api`` endpoints,
        which stay blocked below), so no chats are exposed — the same
        display-vs-enforcement split as the main_ui maintenance overlay. Data and
        action endpoints are refused server-side: ``/api/*`` gets a 401 JSON,
        every other protected page redirects to the shell.
        """
        if request.endpoint in _PUBLIC_ENDPOINTS:
            return None
        if is_authed():
            return None
        if request.endpoint == "database.index":
            return None  # render the shell; login overlay shown, data blocked below
        if request.path.startswith("/api/"):
            return jsonify({"error": "auth_required"}), 401
        return redirect(url_for("database.index"))
