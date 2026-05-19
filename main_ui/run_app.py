"""Flask app for the main_ui production-shape tutor."""

from __future__ import annotations

from flask import Flask, Response, g, jsonify, request

from main_ui.config import load_config
from main_ui.cookies import (
    SESSION_COOKIE_NAME,
    default_cookie_kwargs,
    new_session_id,
)
from main_ui.db import SessionLocal
from main_ui.routes.chat import chat_bp
from main_ui.routes.email import email_bp
from main_ui.routes.embed import embed_bp
from main_ui.routes.history import history_bp
from main_ui.routes.identity import identity_bp


def create_app() -> Flask:
    config = load_config()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key

    app.register_blueprint(embed_bp)
    app.register_blueprint(identity_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(email_bp)
    app.register_blueprint(history_bp)

    @app.before_request
    def _ensure_session_id() -> None:
        existing = request.cookies.get(SESSION_COOKIE_NAME)
        if existing:
            g.session_id = existing
            g.session_id_is_new = False
        else:
            g.session_id = new_session_id()
            g.session_id_is_new = True

    @app.before_request
    def _open_db_session() -> None:
        g.db = SessionLocal()

    @app.teardown_request
    def _close_db_session(exception: BaseException | None = None) -> None:
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
        if getattr(g, "session_id_is_new", False):
            response.set_cookie(
                SESSION_COOKIE_NAME,
                g.session_id,
                **default_cookie_kwargs(),
            )
        return response

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "main_ui"})

    return app


app = create_app()
