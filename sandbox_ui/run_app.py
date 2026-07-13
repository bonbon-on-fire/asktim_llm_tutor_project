"""Flask app for the sandbox_ui tutor testing harness."""

from __future__ import annotations

from sqlalchemy import inspect, text

from sandbox_ui.config import load_config
from sandbox_ui.db import SessionLocal
from sandbox_ui.db.models import Base
from sandbox_ui.db.session import engine
from sandbox_ui.routes.chat import chat_bp
from sandbox_ui.routes.embed import embed_bp
from sandbox_ui.routes.feedback import feedback_bp
from sandbox_ui.routes.history import history_bp
from sandbox_ui.routes.identity import identity_bp
from sandbox_ui.routes.message_rating import message_rating_bp
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


def _migrate_email_to_username() -> None:
    """Finish the ``email`` -> ``username`` rename on the long-lived Sandbox DB.

    sandbox_ui skips Alembic, so the rename main_ui applied via migration never
    ran here. ``_reconcile_columns`` above already ADDED the new nullable
    ``username`` column, but the legacy ``email`` column survives — and on
    ``students`` it's the NOT NULL primary key, so every identity insert (which
    supplies only ``username``) fails with NotNullViolation. This completes the
    rename idempotently on boot: backfill ``username`` from ``email``, move the
    primary key / NOT NULL onto ``username``, and drop the dead ``email``
    column. A no-op once ``email`` is gone, and race-safe across gunicorn
    workers (each step is guarded and the whole table repair is one atomic
    transaction, so a worker that loses the race just rolls back).

    Postgres-only: local SQLite builds a fresh schema straight from the models,
    so the legacy ``email`` column never exists there and there is nothing to do.
    """
    if engine.dialect.name != "postgresql":
        return

    inspector = inspect(engine)
    tables = set(inspector.get_table_names())

    def _cols(table_name: str) -> set[str]:
        return {c["name"] for c in inspector.get_columns(table_name)}

    # students: email is the legacy NOT NULL primary key; username was added
    # nullable by _reconcile_columns. Promote username to the PK, drop email.
    if "students" in tables and {"email", "username"} <= _cols("students"):
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("UPDATE students SET username = email WHERE username IS NULL")
                )
                conn.execute(
                    text("ALTER TABLE students DROP CONSTRAINT IF EXISTS students_pkey")
                )
                conn.execute(text("ALTER TABLE students ALTER COLUMN username SET NOT NULL"))
                conn.execute(text("ALTER TABLE students ADD PRIMARY KEY (username)"))
                conn.execute(text("ALTER TABLE students DROP COLUMN email"))
        except Exception:
            # A racing worker already completed the rename — email ends up gone
            # either way.
            pass

    # conversations: email is a legacy nullable column superseded by username.
    if "conversations" in tables and {"email", "username"} <= _cols("conversations"):
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE conversations SET username = email "
                        "WHERE username IS NULL AND email IS NOT NULL"
                    )
                )
                conn.execute(text("DROP INDEX IF EXISTS idx_conversations_email"))
                conn.execute(text("ALTER TABLE conversations DROP COLUMN email"))
        except Exception:
            pass


def _drop_custom_context_columns(engine) -> None:
    """One-time: drop the removed custom_* Conversation columns if present.

    Sandbox has no Alembic; this mirrors the hand-rolled boot reconciler. Idempotent
    and safe on a fresh DB (create_all never creates these now) and on both SQLite
    (local dev) and Postgres (prod). The dropped snapshots are disposable test data.
    """
    removed = (
        "custom_course_text",
        "custom_exercise_text",
        "custom_tutor_prompt",
        "custom_syllabus_text",
        "custom_lectures_text",
    )
    inspector = inspect(engine)
    if "conversations" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("conversations")}
    to_drop = [name for name in removed if name in existing]
    if not to_drop:
        return
    for name in to_drop:
        # Each drop in its own transaction, guarded — under multi-worker gunicorn
        # (no --preload) every worker runs this on boot and races. A worker that
        # loses the race sees the column already gone and Postgres raises
        # UndefinedColumn; swallow it (a poisoned transaction can't batch the rest,
        # so one statement per transaction). Mirrors _reconcile_columns /
        # _migrate_email_to_username, which guard the same race.
        try:
            with engine.begin() as conn:
                conn.execute(text(f'ALTER TABLE conversations DROP COLUMN {name}'))
        except Exception:
            pass


app = create_app(
    import_name=__name__,
    config=load_config(),
    service_name="sandbox_ui",
    session_local=SessionLocal,
    blueprints=[embed_bp, identity_bp, chat_bp, history_bp, feedback_bp, message_rating_bp],
    # sandbox_ui owns a separate, throwaway database and skips Alembic — the
    # schema is created directly from the models on boot. create_all makes
    # missing tables; _reconcile_columns backfills columns added to tables
    # that already existed (e.g. uploaded_images.data); _migrate_email_to_username
    # finishes the email->username rename (which reconcile can't, since it only
    # adds columns) so the long-lived Sandbox DB never needs a manual reset;
    # _drop_custom_context_columns removes the retired custom_* snapshot columns.
    on_startup=lambda: (
        Base.metadata.create_all(engine),
        _reconcile_columns(),
        _migrate_email_to_username(),
        _drop_custom_context_columns(engine),
    ),
)
