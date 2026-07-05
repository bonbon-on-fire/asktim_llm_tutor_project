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
