"""POST /api/email — best-effort student identity capture.

Triggered by the frontend modal that appears after the 3rd student message.
Validates that the supplied email contains `@` and `.` (per the 2026-05-08
meeting notes — "wrong emails are still useful for correlation"), sets the
`tutor_email` cookie, and backfills any Conversations from the same session
that were created before the email was known.

JSON request:
    { "email": "alice@example.edu" }

JSON response (200):
    { "email": "alice@example.edu", "backfilled_conversations": N }

Error response (400):
    { "error": "invalid_email", "reason": "..." }
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from main_ui.cookies import EMAIL_COOKIE_NAME, default_cookie_kwargs
from main_ui.services.conversation import backfill_email_for_session


email_bp = Blueprint("email", __name__)


def _validate_email(value) -> str | None:
    """Return None if value passes the soft validation, else a reason string."""
    if not isinstance(value, str):
        return "must be a string"
    cleaned = value.strip()
    if not cleaned:
        return "missing"
    if "@" not in cleaned or "." not in cleaned:
        return "must contain @ and ."
    return None


@email_bp.post("/api/email")
def submit_email():
    data = request.get_json(silent=True) or {}
    raw_email = data.get("email")
    reason = _validate_email(raw_email)
    if reason:
        return jsonify({"error": "invalid_email", "reason": reason}), 400

    email = raw_email.strip()
    backfilled = backfill_email_for_session(g.db, g.session_id, email)

    response = jsonify(
        {
            "email": email,
            "backfilled_conversations": backfilled,
        }
    )
    response.set_cookie(EMAIL_COOKIE_NAME, email, **default_cookie_kwargs())
    return response
