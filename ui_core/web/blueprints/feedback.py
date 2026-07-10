"""Feedback route — ``POST /api/feedback`` records a 1..5 tutor rating.

A student can rate the conversation from a small mid-session notification. The
rating is scoped to the conversation (not a single message); ``turn`` records
where in the conversation it was given.

Shared body for ``main_ui`` and ``sandbox_ui`` (byte-identical apart from import
paths) — built as a factory so each app injects its own ``cookies`` /
``services.conversation`` / ``services.feedback`` modules (mirrors
:func:`ui_core.web.blueprints.identity.make_identity_bp`).
"""

from __future__ import annotations

from types import ModuleType
from uuid import UUID

from flask import Blueprint, g, jsonify, request


def make_feedback_bp(
    *, cookies: ModuleType, conversation: ModuleType, feedback: ModuleType
) -> Blueprint:
    """Build the feedback blueprint bound to one app's cookies/services."""
    bp = Blueprint("feedback", __name__)

    @bp.post("/api/feedback")
    def submit_feedback():
        """Record a 1..5 rating for a conversation owned by the current session."""
        data = request.get_json(silent=True) or {}

        # rating: required integer 1..5.
        try:
            rating = int(data.get("rating"))
        except (TypeError, ValueError):
            return jsonify({"error": "bad_rating", "reason": "rating must be an integer 1-5"}), 400
        if not (1 <= rating <= 5):
            return jsonify({"error": "bad_rating", "reason": "rating must be between 1 and 5"}), 400

        # turn: optional integer (where in the conversation the rating was given).
        turn = data.get("turn")
        if turn is not None:
            try:
                turn = int(turn)
            except (TypeError, ValueError):
                turn = None

        # conversation must exist and belong to this session.
        convo_id_raw = data.get("conversation_id")
        if not convo_id_raw:
            return jsonify({"error": "missing_conversation", "reason": "conversation_id is required"}), 400
        try:
            convo_id = UUID(str(convo_id_raw))
        except (ValueError, TypeError):
            return jsonify({"error": "bad_conversation_id", "reason": "conversation_id must be a UUID string"}), 400
        username = request.cookies.get(cookies.USERNAME_COOKIE_NAME)
        convo = conversation.get_conversation_for_viewer(g.db, convo_id, g.session_id, username)
        if convo is None:
            return (
                jsonify(
                    {
                        "error": "wrong_session",
                        "reason": "conversation not found or not owned by this session",
                    }
                ),
                403,
            )

        feedback.record_feedback(g.db, conversation_id=convo.id, turn=turn, rating=rating)
        return jsonify({"ok": True})

    return bp
