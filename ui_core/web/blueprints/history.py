"""Conversation-history endpoints.

- GET /api/history                  list past conversations linked to the
                                    current `tutor_username` cookie
- GET /api/conversation/<uuid>      read-only message log for a single
                                    conversation; accessible if owned by
                                    the current session_id OR username

Both endpoints are read-only and never call the LLM. Unauthorized detail
requests return 404 (not 403) so probing UUIDs can't distinguish
"exists but not yours" from "doesn't exist".

Shared body for ``main_ui`` and ``sandbox_ui`` (byte-identical apart from
import paths) — built as a factory so each app can inject its own
``cookies``, ``services.conversation``, and ``services.images`` modules.
"""

from __future__ import annotations

from types import ModuleType
from urllib.parse import quote
from uuid import UUID

from flask import Blueprint, Response, g, jsonify, request


def content_disposition_attachment(filename: str) -> str:
    """Build a safe ``Content-Disposition: attachment`` header value.

    Student-uploaded filenames are untrusted, so they can carry quotes,
    newlines, or non-ASCII characters that would break (or inject into) the
    header. Emit an ASCII-only ``filename=`` fallback plus an RFC 5987
    ``filename*=`` with the real name percent-encoded — the same shape Flask's
    ``send_file`` uses.
    """
    ascii_fallback = filename.encode("ascii", "ignore").decode("ascii")
    ascii_fallback = ascii_fallback.replace("\\", "_").replace('"', "_")
    ascii_fallback = ascii_fallback.replace("\r", "_").replace("\n", "_")
    if not ascii_fallback:
        ascii_fallback = "download"
    encoded = quote(filename, safe="")
    return f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"


def make_history_bp(
    *,
    cookies: ModuleType,
    conversation: ModuleType,
    images: ModuleType,
    files: ModuleType,
) -> Blueprint:
    """Build the ``history`` blueprint, injecting the app-specific modules.

    ``cookies`` — the app's ``cookies`` module (``USERNAME_COOKIE_NAME``);
    ``conversation`` — the app's ``services.conversation`` module
    (``get_conversation_for_viewer``, ``get_messages_for_conversation``,
    ``list_conversations_for_username``); ``images`` — the app's
    ``services.images`` module (``get_image_for_viewer``); ``files`` — the
    app's ``services.files`` module (``get_file_for_viewer``).
    """

    history_bp = Blueprint("history", __name__)

    @history_bp.get("/api/history")
    def history():
        """List past conversations linked to the current ``username`` cookie (empty if none)."""
        username = cookies.read_username_cookie(request)
        conversations = (
            conversation.list_conversations_for_username(g.db, username)
            if username
            else []
        )
        return jsonify({"username": username, "conversations": conversations})

    @history_bp.get("/api/conversation/<conversation_id>")
    def conversation_detail(conversation_id: str):
        """Return the read-only message log for one owned conversation.

        Responds 400 for a malformed UUID and 404 when the conversation is
        unknown or not owned by the current session_id / username.
        """
        try:
            convo_id = UUID(conversation_id)
        except (ValueError, TypeError):
            return (
                jsonify(
                    {"error": "bad_conversation_id", "reason": "must be a UUID string"}
                ),
                400,
            )

        username = cookies.read_username_cookie(request)
        convo = conversation.get_conversation_for_viewer(
            g.db, convo_id, g.session_id, username
        )
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
                # sandbox_ui-only: which LLM the tutor ran on for this conversation.
                # main_ui's Conversation has no such column, so getattr yields None
                # there (harmless — main_ui's frontend doesn't read it).
                "provider": getattr(convo, "provider", None),
                "messages": conversation.get_messages_for_conversation(g.db, convo),
            }
        )

    @history_bp.get("/api/image/<int:image_id>")
    def image(image_id: int):
        """Serve a student-uploaded image's bytes if the viewer owns its conversation.

        Ownership is by session_id or username (same rule as conversation detail).
        Unauthorized/unknown ids return 404 so they can't be probed.
        """
        username = cookies.read_username_cookie(request)
        img = images.get_image_for_viewer(g.db, image_id, g.session_id, username)
        if img is None:
            return jsonify({"error": "not_found"}), 404
        return Response(
            img.data,
            mimetype=img.mime_type,
            headers={"Cache-Control": "private, max-age=86400"},
        )

    @history_bp.get("/api/file/<int:file_id>")
    def file(file_id: int):
        """Serve a student-uploaded non-image file's bytes as a download.

        Ownership is by session_id or username (same rule as the image
        endpoint). Unauthorized/unknown ids return 404 so they can't be
        probed. Served with ``Content-Disposition: attachment`` so the
        browser downloads it under its original filename.
        """
        username = cookies.read_username_cookie(request)
        row = files.get_file_for_viewer(g.db, file_id, g.session_id, username)
        if row is None:
            return jsonify({"error": "not_found"}), 404
        return Response(
            row.data,
            mimetype="application/octet-stream",
            headers={
                "Content-Disposition": content_disposition_attachment(row.filename),
                "Cache-Control": "private, max-age=86400",
            },
        )

    return history_bp
