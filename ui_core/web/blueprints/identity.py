"""Identity routes — session state plus username+password linking.

`GET  /api/whoami`   — current session/username/conversation state.
`POST /api/identity` — link the current session to a username by setting a
                      password (creates the student row on first use, or
                      verifies the password on subsequent uses).

This is soft identity, not real auth. The browser cookie `tutor_username`
remains the active session-identity carrier; the password is checked
exactly once, when a username is first linked to a session.

Shared body for ``main_ui`` and ``sandbox_ui`` (byte-identical apart from
import paths) — built as a factory so each app can inject its own
``cookies`` module and ``services.conversation`` / ``services.students``
modules.
"""

from __future__ import annotations

from types import ModuleType

from flask import Blueprint, g, jsonify, request

MAX_USERNAME_LENGTH = 100


def _validate_username(value) -> str | None:
    if not isinstance(value, str):
        return "must be a string"
    cleaned = value.strip()
    if not cleaned:
        return "missing"
    if len(cleaned) > MAX_USERNAME_LENGTH:
        return f"must be at most {MAX_USERNAME_LENGTH} characters"
    return None


def _validate_password(value, *, students: ModuleType) -> str | None:
    if not isinstance(value, str):
        return "must be a string"
    if len(value) < students.MIN_PASSWORD_LENGTH:
        return f"must be at least {students.MIN_PASSWORD_LENGTH} characters"
    return None


def make_identity_bp(
    *, cookies: ModuleType, conversation: ModuleType, students: ModuleType
) -> Blueprint:
    """Build the ``identity`` blueprint, injecting the app-specific modules.

    ``cookies`` — the app's ``cookies`` module (``USERNAME_COOKIE_NAME``,
    ``default_cookie_kwargs``); ``conversation`` — the app's
    ``services.conversation`` module (``backfill_username_for_session``);
    ``students`` — the app's ``services.students`` module
    (``MIN_PASSWORD_LENGTH``, ``WeakPasswordError``, ``create_student``,
    ``get_student``, ``verify_password``).
    """

    identity_bp = Blueprint("identity", __name__)

    @identity_bp.get("/api/whoami")
    def whoami():
        return jsonify(
            {
                "session_id": getattr(g, "session_id", None),
                "username": request.cookies.get(cookies.USERNAME_COOKIE_NAME),
                "conversation_id": None,
            }
        )

    @identity_bp.post("/api/identity/check")
    def check_identity():
        """Probe whether a username already has a password registered.

        Used by the two-step modal: the frontend POSTs the username here, learns
        whether to ask the student to *create* a password or *enter* their
        existing one, then sends the full ``{username, password}`` to
        ``/api/identity`` on stage 2.

        JSON request:  { "username": "alice" }
        JSON success:  { "username": "alice", "exists": true|false }

        Error:
            400 invalid_username — username missing or too long
        """
        data = request.get_json(silent=True) or {}
        username_reason = _validate_username(data.get("username"))
        if username_reason:
            return jsonify({"error": "invalid_username", "reason": username_reason}), 400

        username = data["username"].strip()
        student = students.get_student(g.db, username)
        return jsonify({"username": username, "exists": student is not None})

    @identity_bp.post("/api/identity")
    def submit_identity():
        """Link the current session to a username via password.

        JSON request:
            { "username": "alice", "password": "..." }

        Response shape is identical whether the username is new or pre-existing —
        the only signal that the password was checked is the 401 on mismatch.

        JSON success (200):
            { "username": "...", "backfilled_conversations": N }

        Errors:
            400 invalid_username — username missing or too long
            400 weak_password    — password shorter than minimum
            401 wrong_password   — username exists but password doesn't match
        """
        data = request.get_json(silent=True) or {}

        username_reason = _validate_username(data.get("username"))
        if username_reason:
            return jsonify({"error": "invalid_username", "reason": username_reason}), 400

        password_reason = _validate_password(data.get("password"), students=students)
        if password_reason:
            return jsonify({"error": "weak_password", "reason": password_reason}), 400

        username = data["username"].strip()
        password = data["password"]

        db = g.db
        existing = students.get_student(db, username)
        if existing is None:
            try:
                students.create_student(db, username=username, password=password)
            except students.WeakPasswordError as exc:
                return jsonify({"error": "weak_password", "reason": str(exc)}), 400
        else:
            if not students.verify_password(existing, password):
                return (
                    jsonify(
                        {
                            "error": "wrong_password",
                            "reason": "username and password don't match",
                        }
                    ),
                    401,
                )

        backfilled = conversation.backfill_username_for_session(db, g.session_id, username)

        response = jsonify(
            {"username": username, "backfilled_conversations": backfilled}
        )
        response.set_cookie(
            cookies.USERNAME_COOKIE_NAME, username, **cookies.default_cookie_kwargs()
        )
        return response

    return identity_bp
