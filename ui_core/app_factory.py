"""Shared Flask app-assembly factory for the chat UIs (``main_ui``, ``sandbox_ui``).

Collapses the boilerplate that was duplicated across those two apps'
``run_app.py`` modules: Flask construction, the ``ui_core`` template loader,
blueprint registration, session-id/db-session before/teardown hooks, the
session-cookie after_request, and the ``/health`` endpoint.

``database_ui`` is structurally different (read-only, password gate, no chat)
and does not use this factory.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Sequence

from flask import Blueprint, Flask, Response, g, jsonify, request
from jinja2 import ChoiceLoader, FileSystemLoader

import ui_core
from ui_core.cookies import SESSION_COOKIE_NAME, default_cookie_kwargs, new_session_id
from ui_core.web.static_blueprint import static_bp


# Endpoints that stay reachable while maintenance mode is on — just enough to
# render the maintenance page and its assets. Everything else (the chat API and
# every other /api/* action) is refused server-side with 503, so the outage holds
# even if a client deletes the overlay from the DOM. This mirrors database_ui's
# before_request gate (database_ui/auth.py), which likewise allowlists a few
# public endpoints and blocks the rest.
_MAINTENANCE_ALLOWED_ENDPOINTS = frozenset(
    {
        "embed.index",    # GET /       — serves the page (with the overlay)
        "embed.embed",    # GET /embed  — same, with course context
        "static",         # /static/*   — vendored JS (marked, dompurify, chat.js)
        "ui_core.static",  # /ui-core/*  — chat.css (overlay styles) + katex
        "health",         # Railway liveness probe must keep passing
        # main_ui's diagnostic endpoint — external monitors and chat.js's outage
        # confirmation probe must keep reading it even during manual maintenance.
        # (Registered only in main_ui; harmlessly never matches in sandbox_ui.)
        "health_detail.detail",
    }
)


def create_app(
    *,
    import_name: str,
    config,
    service_name: str,
    session_local: Callable[[], object],
    blueprints: Sequence[Blueprint],
    on_startup: Callable[[], None] | None = None,
) -> Flask:
    """Assemble and return a configured Flask app for a chat UI.

    Wires up the ``ui_core`` template loader, registers the static blueprint
    plus the caller's ``blueprints``, installs the session-id / db-session
    request hooks and the session-cookie ``after_request``, and adds
    ``/health``. ``session_local`` is the per-app DB session factory,
    ``service_name`` is echoed by ``/health``, and ``on_startup`` (if given)
    runs once after wiring.
    """
    app = Flask(import_name)
    app.config["SECRET_KEY"] = config.secret_key

    ui_core_templates = Path(ui_core.__file__).resolve().parent / "templates"
    app.jinja_loader = ChoiceLoader(
        [app.jinja_loader, FileSystemLoader(str(ui_core_templates))]
    )

    app.register_blueprint(static_bp)
    for bp in blueprints:
        app.register_blueprint(bp)

    # Read once at startup: both flags are set at deploy time and a change
    # restarts the process (sandbox_ui has neither field, hence getattr defaults).
    # Maintenance is a global outage (blocks every course). Exam lockdown is a
    # deliberate closure scoped per course: `exam_lockdown_all` locks every course
    # (legacy bare-truthy value), else only the courses in `exam_lockdown_courses`.
    maintenance_mode = bool(getattr(config, "maintenance_mode", False))
    exam_lockdown_all = bool(getattr(config, "exam_lockdown_all", False))
    exam_lockdown_courses = frozenset(getattr(config, "exam_lockdown_courses", ()))
    exam_lockdown_active = exam_lockdown_all or bool(exam_lockdown_courses)

    def _request_course() -> str | None:
        """Best-effort read of the request's course, for per-course exam scoping.

        POST /api/chat carries ``course`` in its form (multipart) or JSON body;
        get_json(silent=True) caches the parse so the chat handler re-reads it
        cleanly. Everything else may carry it as a query param. Endpoints with no
        course (e.g. /api/history) return None and so are never course-locked.
        """
        if request.method == "POST":
            if (request.content_type or "").startswith("multipart/form-data"):
                return request.form.get("course")
            data = request.get_json(silent=True)
            if isinstance(data, dict):
                return data.get("course")
        return request.args.get("course")

    @app.before_request
    def _maintenance_gate():
        """Refuse functional endpoints while maintenance or exam lockdown is on (503).

        Server-side companion to the overlay: the page still renders (the embed
        endpoints stay allowed, so the overlay shows), but the chat API and every
        other action are blocked here — so the lockout can't be clicked past by
        removing the overlay client-side. Registered first so a blocked request
        short-circuits before the session/DB hooks run. Mirrors database_ui's
        before_request auth gate.

        Maintenance blocks everything; exam lockdown blocks only requests for a
        locked course (an unlisted or course-less request passes through).
        """
        if not (maintenance_mode or exam_lockdown_active):
            return None
        if request.endpoint in _MAINTENANCE_ALLOWED_ENDPOINTS:
            return None
        # Maintenance is the broader, global block, so it's checked first.
        if maintenance_mode:
            payload = {
                "error": "maintenance",
                "message": "AskTIM is temporarily down for maintenance.",
            }
        elif exam_lockdown_all or _request_course() in exam_lockdown_courses:
            payload = {
                "error": "exam_lockdown",
                "message": "AskTIM is unavailable during the exam period.",
            }
        else:
            # Exam lockdown is on but not for this course — serve normally.
            return None
        response = jsonify(payload)
        response.status_code = 503
        response.headers["Retry-After"] = "120"
        return response

    @app.before_request
    def _ensure_session_id() -> None:
        """Populate ``g.session_id`` from the request cookie, minting a new one if absent."""
        existing = request.cookies.get(SESSION_COOKIE_NAME)
        if existing:
            g.session_id = existing
            g.session_id_is_new = False
        else:
            g.session_id = new_session_id()
            g.session_id_is_new = True

    @app.before_request
    def _open_db_session() -> None:
        """Open a per-request DB session on ``g.db``."""
        g.db = session_local()

    @app.teardown_request
    def _close_db_session(exception: BaseException | None = None) -> None:
        """Commit (or roll back on *exception*) and close the request's ``g.db`` session."""
        # Routes that take over their own session lifecycle (the streaming
        # /api/chat endpoint) pop g.db themselves before returning; this
        # teardown then finds nothing to clean up and exits silently.
        db = g.pop("db", None)
        if db is None:
            return
        try:
            if exception is None:
                db.commit()
            else:
                db.rollback()
        finally:
            db.close()

    @app.after_request
    def _set_session_cookie(response: Response) -> Response:
        """Attach the session cookie to *response* when the session id was newly minted."""
        if getattr(g, "session_id_is_new", False):
            response.set_cookie(
                SESSION_COOKIE_NAME,
                g.session_id,
                **default_cookie_kwargs(
                    secure=config.cookie_secure,
                    max_age=config.cookie_max_age_seconds,
                ),
            )
        return response

    @app.get("/health")
    def health():
        """Return a JSON liveness payload identifying this service."""
        return jsonify({"status": "ok", "service": service_name})

    if on_startup is not None:
        on_startup()

    return app
