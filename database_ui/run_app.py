"""Flask app for database_ui — read-only conversation review.

Phase 1 establishes the app factory, per-request read-only DB session, and a
health check. Routes (the conversation list, transcript view, image serving) are
registered in Phase 2. This app intentionally does NOT create or migrate any
schema — the live apps own it; we only read.
"""

from __future__ import annotations

from datetime import timedelta

from flask import Flask, g, jsonify

from database_ui.auth import init_auth
from database_ui.config import load_config
from database_ui.db import SessionLocal
from database_ui.routes.analytics import analytics_bp
from database_ui.routes.database import database_bp
from ui_core.web.static_blueprint import static_bp


def create_app() -> Flask:
    """Build and configure the read-only Flask app (config, DB session, routes)."""
    config = load_config()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key
    # Surfaced to templates: title + accent (matches main_ui).
    app.config["DATABASE_UI_TITLE"] = config.title
    app.config["DATABASE_UI_ACCENT"] = config.accent
    # Read by the auth gate; None => open (local dev only).
    app.config["DATABASE_UI_PASSWORD"] = config.password
    # {password: (course_key, ...)} for scoped logins; {} => only the master
    # password (or open dev) is active. Read by the auth gate.
    app.config["DATABASE_UI_COURSE_PASSWORDS"] = config.course_passwords
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(
        seconds=config.cookie_max_age_seconds
    )

    # NOTE: deliberately no Base.metadata.create_all / migrations. read-only.

    @app.before_request
    def _open_db_session() -> None:
        """Open a fresh DB session on ``g.db`` for the current request."""
        g.db = SessionLocal()

    @app.teardown_request
    def _close_db_session(exception: BaseException | None = None) -> None:
        """Roll back (this app never writes) and close the request's DB session."""
        db = g.pop("db", None)
        if db is None:
            return
        # Always roll back — this app never writes. Then close.
        db.rollback()
        db.close()

    @app.get("/health")
    def health():
        """Return a simple JSON health-check payload."""
        return jsonify({"status": "ok", "service": "database_ui"})

    init_auth(app)
    app.register_blueprint(static_bp)
    app.register_blueprint(database_bp)
    app.register_blueprint(analytics_bp)

    return app


app = create_app()
