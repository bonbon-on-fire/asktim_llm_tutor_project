"""Flask app for the sandbox_ui tutor testing harness."""

from __future__ import annotations

from flask import Flask, Response, g, jsonify, request
from sqlalchemy import inspect, text

from sandbox_ui.config import load_config
from sandbox_ui.cookies import (
    SESSION_COOKIE_NAME,
    default_cookie_kwargs,
    new_session_id,
)
from sandbox_ui.db import SessionLocal
from sandbox_ui.db.models import Base
from sandbox_ui.db.session import engine
from sandbox_ui.routes.chat import chat_bp
from sandbox_ui.routes.embed import embed_bp
from sandbox_ui.routes.history import history_bp
from sandbox_ui.routes.identity import identity_bp
from ui_core.web.static_blueprint import static_bp


def _reconcile_columns() -> None:
    """Add model columns missing from already-existing tables.

    sandbox_ui skips Alembic and builds its schema with ``create_all`` — but
    ``create_all`` only creates *missing tables*, it never adds columns to a
    table that already exists. The Sandbox DB is long-lived (Railway
    ``asktim_test``), so a model change like the image-upload
    ``uploaded_images.data`` (BYTEA) column would otherwise fail every insert
    with ``UndefinedColumn`` until someone manually reset the database.

    This reconciles that drift on boot: for each existing table, any column the
    model declares but the DB lacks is added (nullable, so existing rows are
    fine; every insert path supplies a value). Idempotent and race-safe across
    gunicorn workers.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    is_postgres = engine.dialect.name == "postgresql"
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if table.name not in existing_tables:
                continue  # create_all just built it fresh — nothing to reconcile
            have = {c["name"] for c in inspector.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                ddl_type = col.type.compile(dialect=engine.dialect)
                if_not_exists = "IF NOT EXISTS " if is_postgres else ""
                try:
                    conn.execute(
                        text(
                            f'ALTER TABLE "{table.name}" '
                            f'ADD COLUMN {if_not_exists}"{col.name}" {ddl_type}'
                        )
                    )
                except Exception:
                    # A racing worker already added it (or the backend lacks
                    # IF NOT EXISTS) — the column ends up present either way.
                    pass


def create_app() -> Flask:
    config = load_config()
    app = Flask(__name__)
    app.config["SECRET_KEY"] = config.secret_key

    # sandbox_ui owns a separate, throwaway database and skips Alembic — the
    # schema is created directly from the models on boot. create_all makes
    # missing tables; _reconcile_columns backfills columns added to tables that
    # already existed (e.g. uploaded_images.data) so the long-lived Sandbox DB
    # never needs a manual reset.
    Base.metadata.create_all(engine)
    _reconcile_columns()

    app.register_blueprint(static_bp)
    app.register_blueprint(embed_bp)
    app.register_blueprint(identity_bp)
    app.register_blueprint(chat_bp)
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
        if getattr(g, "session_id_is_new", False):
            response.set_cookie(
                SESSION_COOKIE_NAME,
                g.session_id,
                **default_cookie_kwargs(),
            )
        return response

    @app.get("/health")
    def health():
        return jsonify({"status": "ok", "service": "sandbox_ui"})

    return app


app = create_app()
