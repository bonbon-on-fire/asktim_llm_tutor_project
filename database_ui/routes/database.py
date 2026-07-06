"""Read-only review routes.

Page:
- GET  /            the review shell (sidebar + transcript view)
- GET  /login       shared-password login form
- POST /login       verify password, start session
- GET  /logout      clear session

API (all read-only, all behind the auth gate except where noted):
- GET /api/conversations            list ALL conversations (sort=date|student)
- GET /api/conversation/<uuid>      one conversation's full transcript
- GET /api/image/<int>              serve an uploaded image's bytes

Unlike the live apps' history endpoints, these are intentionally NOT scoped to a
viewer's session/email — the whole point is to review everyone's conversations.
"""

from __future__ import annotations

from uuid import UUID

from flask import (
    Blueprint,
    Response,
    current_app,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from sqlalchemy.exc import SQLAlchemyError

from database_ui.auth import check_password, clear_auth, mark_authed
from database_ui.services import conversations as svc

database_bp = Blueprint("database", __name__)

_VALID_SORTS = {"date", "student"}
_MAX_PAGE = 200

# Substrings various backends use when a query references a column the DB lacks.
# This app is read-only and never migrates; a missing column means the deployed
# schema is behind the models (main_ui owns migrations), so we surface a clear
# "redeploy main" message instead of a generic failure.
_SCHEMA_DRIFT_MARKERS = (
    "does not exist",   # postgres: column "x" does not exist
    "undefinedcolumn",  # postgres error class name
    "no such column",   # sqlite
    "unknown column",   # mysql
)


def _is_schema_drift(exc: Exception) -> bool:
    """True if *exc* reads like a missing-column error from an out-of-date schema."""
    message = str(getattr(exc, "orig", exc)).lower()
    return any(marker in message for marker in _SCHEMA_DRIFT_MARKERS)


@database_bp.get("/")
def index():
    """Render the review shell (sidebar plus transcript view)."""
    return render_template(
        "index.html",
        title=current_app.config["DATABASE_UI_TITLE"],
        accent=current_app.config["DATABASE_UI_ACCENT"],
    )


@database_bp.get("/login")
def login():
    """Render the shared-password login form."""
    return render_template(
        "login.html",
        title=current_app.config["DATABASE_UI_TITLE"],
        accent=current_app.config["DATABASE_UI_ACCENT"],
        error=None,
    )


@database_bp.post("/login")
def login_submit():
    """Verify the submitted password and start a session, or re-render with an error."""
    candidate = request.form.get("password", "")
    if check_password(candidate):
        mark_authed()
        return redirect(url_for("database.index"))
    return (
        render_template(
            "login.html",
            title=current_app.config["DATABASE_UI_TITLE"],
            accent=current_app.config["DATABASE_UI_ACCENT"],
            error="Incorrect password.",
        ),
        401,
    )


@database_bp.get("/logout")
def logout():
    """Clear the session and redirect to the login page."""
    clear_auth()
    return redirect(url_for("database.login"))


@database_bp.get("/api/conversations")
def api_conversations():
    """List all conversations as JSON, sorted by ``date`` or ``student`` with paging."""
    sort = request.args.get("sort", "date")
    if sort not in _VALID_SORTS:
        sort = "date"
    limit = _clamp_int(request.args.get("limit"), default=None, lo=1, hi=_MAX_PAGE)
    offset = _clamp_int(request.args.get("offset"), default=0, lo=0, hi=None)
    try:
        conversations = svc.list_all_conversations(
            g.db, sort=sort, limit=limit, offset=offset
        )
    except SQLAlchemyError as exc:
        g.db.rollback()
        if _is_schema_drift(exc):
            current_app.logger.error("conversations query failed on schema drift: %s", exc)
            return (
                jsonify(
                    {
                        "error": "schema_outdated",
                        "message": "Redeploy askTIM-main to run migrations",
                    }
                ),
                503,
            )
        current_app.logger.exception("conversations query failed")
        return jsonify({"error": "query_failed", "message": "Could not load conversations"}), 500
    return jsonify({"sort": sort, "conversations": conversations})


@database_bp.get("/api/conversation/<conversation_id>")
def api_conversation(conversation_id: str):
    """Return one conversation's metadata and full transcript as JSON.

    Responds 400 for a malformed id and 404 when no such conversation exists.
    """
    try:
        convo_id = UUID(conversation_id)
    except (ValueError, TypeError):
        return jsonify({"error": "bad_conversation_id"}), 400
    convo = svc.get_conversation(g.db, convo_id)
    if convo is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(
        {
            "id": str(convo.id),
            "email": convo.username,
            "session_id": convo.session_id,
            "course": convo.course,
            "exercise_number": convo.exercise_number,
            "tutor_prompt": convo.tutor_prompt,
            "started_at": convo.started_at.isoformat() if convo.started_at else None,
            "last_active_at": (
                convo.last_active_at.isoformat() if convo.last_active_at else None
            ),
            "messages": svc.get_messages_for_conversation(g.db, convo),
        }
    )


@database_bp.get("/api/image/<int:image_id>")
def api_image(image_id: int):
    """Serve an uploaded image's bytes, or 404 if the image is not found."""
    img = svc.get_image(g.db, image_id)
    if img is None:
        return jsonify({"error": "not_found"}), 404
    return Response(
        img.data,
        mimetype=img.mime_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


def _clamp_int(raw, *, default, lo, hi):
    """Parse a query-arg int, clamped to [lo, hi]; *default* on missing/bad."""
    if raw is None or raw == "":
        return default
    try:
        val = int(raw)
    except (ValueError, TypeError):
        return default
    if lo is not None:
        val = max(lo, val)
    if hi is not None:
        val = min(hi, val)
    return val
