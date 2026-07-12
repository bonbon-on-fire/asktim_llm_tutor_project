"""Per-message rating route — ``POST /api/message/<id>/rating``.

A student can thumb a single tutor message up or down (or clear it). The rating
is stored on the message row as ``-1`` (down), ``0`` (none), or ``1`` (up) —
distinct from the conversation-scoped ``feedback`` table.

Shared body for ``main_ui`` and ``sandbox_ui`` — built as a factory so each app
injects its own ``cookies`` / ``services.conversation`` modules (mirrors
:func:`ui_core.web.blueprints.feedback.make_feedback_bp`).
"""

from __future__ import annotations

from types import ModuleType

from flask import Blueprint, g, jsonify, request


def make_message_rating_bp(*, cookies: ModuleType, conversation: ModuleType) -> Blueprint:
    """Build the message-rating blueprint bound to one app's cookies/services."""
    bp = Blueprint("message_rating", __name__)

    @bp.post("/api/message/<int:message_id>/rating")
    def rate_message(message_id: int):
        """Set a tutor message's thumb rating (-1/0/1) if owned by this session."""
        data = request.get_json(silent=True) or {}

        # rating: required, exactly one of -1, 0, 1.
        try:
            rating = int(data.get("rating"))
        except (TypeError, ValueError):
            return jsonify({"error": "bad_rating", "reason": "rating must be -1, 0, or 1"}), 400
        if rating not in (-1, 0, 1):
            return jsonify({"error": "bad_rating", "reason": "rating must be -1, 0, or 1"}), 400

        username = request.cookies.get(cookies.USERNAME_COOKIE_NAME)
        msg = conversation.get_message_for_viewer(g.db, message_id, g.session_id, username)
        if msg is None:
            return (
                jsonify(
                    {
                        "error": "wrong_session",
                        "reason": "message not found or not owned by this session",
                    }
                ),
                403,
            )
        if msg.role != "tutor":
            return (
                jsonify({"error": "not_tutor", "reason": "only tutor messages can be rated"}),
                400,
            )

        conversation.set_message_rating(g.db, msg, rating)
        return jsonify({"ok": True, "rating": rating})

    return bp
