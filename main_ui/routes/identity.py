"""GET /api/whoami — returns the current session/email/conversation state.

In Step 3 only `session_id` is ever populated. `email` is `null` until the
Step 7 email modal flow lands; `conversation_id` is `null` until Step 5
introduces conversations.
"""

from __future__ import annotations

from flask import Blueprint, g, jsonify, request

from main_ui.cookies import EMAIL_COOKIE_NAME


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
