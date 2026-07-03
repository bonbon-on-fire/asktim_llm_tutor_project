"""Flask app for the sandbox_ui tutor testing harness."""

from __future__ import annotations

from sqlalchemy import inspect, text

from sandbox_ui.config import load_config
from sandbox_ui.db import SessionLocal
from sandbox_ui.db.models import Base
from sandbox_ui.db.session import engine
from sandbox_ui.routes.chat import chat_bp
from sandbox_ui.routes.embed import embed_bp
from sandbox_ui.routes.history import history_bp
from sandbox_ui.routes.identity import identity_bp
from ui_core.app_factory import create_app


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


app = create_app(
    import_name=__name__,
    config=load_config(),
    service_name="sandbox_ui",
    session_local=SessionLocal,
    blueprints=[embed_bp, identity_bp, chat_bp, history_bp],
    # sandbox_ui owns a separate, throwaway database and skips Alembic — the
    # schema is created directly from the models on boot. create_all makes
    # missing tables; _reconcile_columns backfills columns added to tables
    # that already existed (e.g. uploaded_images.data) so the long-lived
    # Sandbox DB never needs a manual reset.
    on_startup=lambda: (Base.metadata.create_all(engine), _reconcile_columns()),
)
