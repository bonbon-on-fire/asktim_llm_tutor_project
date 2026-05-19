"""Conversation-history endpoints.

- GET /api/history                  list past conversations linked to the
                                    current `tutor_email` cookie
- GET /api/conversation/<uuid>      read-only message log for a single
                                    conversation; accessible if owned by
                                    the current session_id OR email

Both endpoints are read-only and never call the LLM. Unauthorized detail
requests return 404 (not 403) so probing UUIDs can't distinguish
"exists but not yours" from "doesn't exist".
"""

from __future__ import annotations

from uuid import UUID

from flask import Blueprint, g, jsonify, request

from main_ui.cookies import EMAIL_COOKIE_NAME
from main_ui.services.conversation import (
    get_conversation_for_viewer,
    get_messages_for_conversation,
    list_conversations_for_email,
)


history_bp = Blueprint("history", __name__)


@history_bp.get("/api/history")
def history():
    email = request.cookies.get(EMAIL_COOKIE_NAME)
    conversations = list_conversations_for_email(g.db, email) if email else []
    return jsonify({"email": email, "conversations": conversations})


@history_bp.get("/api/conversation/<conversation_id>")
def conversation_detail(conversation_id: str):
    try:
        convo_id = UUID(conversation_id)
    except (ValueError, TypeError):
        return (
            jsonify(
                {"error": "bad_conversation_id", "reason": "must be a UUID string"}
            ),
            400,
        )

    email = request.cookies.get(EMAIL_COOKIE_NAME)
    convo = get_conversation_for_viewer(g.db, convo_id, g.session_id, email)
    if convo is None:
        return jsonify({"error": "not_found"}), 404

    return jsonify(
        {
            "id": str(convo.id),
            "course": convo.course,
            "exercise_number": convo.exercise_number,
            "tutor_prompt": convo.tutor_prompt,
            "started_at": convo.started_at.isoformat() if convo.started_at else None,
            "last_active_at": (
                convo.last_active_at.isoformat() if convo.last_active_at else None
            ),
            "messages": get_messages_for_conversation(g.db, convo),
        }
    )
