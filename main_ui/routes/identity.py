"""Identity routes — session state plus email+password linking.

`GET  /api/whoami`   — current session/email/conversation state.
`POST /api/identity` — link the current session to an email by setting a
                      password (creates the student row on first use, or
                      verifies the password on subsequent uses).

This is soft identity, not real auth. The browser cookie `tutor_email`
remains the active session-identity carrier; the password is checked
exactly once, when an email is first linked to a session.
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from main_ui.cookies import EMAIL_COOKIE_NAME, default_cookie_kwargs
from main_ui.services.conversation import backfill_email_for_session
from main_ui.services.students import (
    MIN_PASSWORD_LENGTH,
    WeakPasswordError,
    create_student,
    get_student,
    verify_password,
)


identity_bp = Blueprint("identity", __name__)


@identity_bp.get("/api/whoami")
def whoami():
    return jsonify(
        {
            "session_id": getattr(g, "session_id", None),
            "email": request.cookies.get(EMAIL_COOKIE_NAME),
            "conversation_id": None,
        }
    )


def _validate_email(value) -> str | None:
    if not isinstance(value, str):
        return "must be a string"
    cleaned = value.strip()
    if not cleaned:
        return "missing"
    if "@" not in cleaned or "." not in cleaned:
        return "must contain @ and ."
    return None


def _validate_password(value) -> str | None:
    if not isinstance(value, str):
        return "must be a string"
    if len(value) < MIN_PASSWORD_LENGTH:
        return f"must be at least {MIN_PASSWORD_LENGTH} characters"
    return None


@identity_bp.post("/api/identity/check")
def check_identity():
    """Probe whether an email already has a password registered.

    Used by the two-step modal: the frontend POSTs the email here, learns
    whether to ask the student to *create* a password or *enter* their
    existing one, then sends the full ``{email, password}`` to
    ``/api/identity`` on stage 2.

    JSON request:  { "email": "alice@example.edu" }
    JSON success:  { "email": "alice@example.edu", "exists": true|false }

    Error:
        400 invalid_email — email failed @/. check
    """
    data = request.get_json(silent=True) or {}
    email_reason = _validate_email(data.get("email"))
    if email_reason:
        return jsonify({"error": "invalid_email", "reason": email_reason}), 400

    email = data["email"].strip()
    student = get_student(g.db, email)
    return jsonify({"email": email, "exists": student is not None})


@identity_bp.post("/api/identity")
def submit_identity():
    """Link the current session to an email via password.

    JSON request:
        { "email": "alice@example.edu", "password": "..." }

    Response shape is identical whether the email is new or pre-existing —
    the only signal that the password was checked is the 401 on mismatch.

    JSON success (200):
        { "email": "...", "backfilled_conversations": N }

    Errors:
        400 invalid_email   — email failed @/. check
        400 weak_password   — password shorter than minimum
        401 wrong_password  — email exists but password doesn't match
    """
    data = request.get_json(silent=True) or {}

    email_reason = _validate_email(data.get("email"))
    if email_reason:
        return jsonify({"error": "invalid_email", "reason": email_reason}), 400

    password_reason = _validate_password(data.get("password"))
    if password_reason:
        return jsonify({"error": "weak_password", "reason": password_reason}), 400

    email = data["email"].strip()
    password = data["password"]

    db = g.db
    existing = get_student(db, email)
    if existing is None:
        try:
            create_student(db, email=email, password=password)
        except WeakPasswordError as exc:
            return jsonify({"error": "weak_password", "reason": str(exc)}), 400
    else:
        if not verify_password(existing, password):
            return (
                jsonify(
                    {
                        "error": "wrong_password",
                        "reason": "email and password don't match",
                    }
                ),
                401,
            )

    backfilled = backfill_email_for_session(db, g.session_id, email)

    response = jsonify(
        {"email": email, "backfilled_conversations": backfilled}
    )
    response.set_cookie(EMAIL_COOKIE_NAME, email, **default_cookie_kwargs())
    return response
