"""Shared SQLAlchemy engine + session helpers for the web apps.

Each app builds its engine and session factory from these helpers, passing the
behavior knobs that used to be hard-coded per app:

- ``sqlite_fk``: enable SQLite foreign-key enforcement on connect (main/sandbox).
- ``pool_pre_ping``: guard stale connections to a long-lived remote DB (database_ui).
- ``normalize_pg``: rewrite ``postgres://`` / ``postgresql://`` to
  ``postgresql+psycopg://`` so SQLAlchemy uses psycopg3 (database_ui; the live
  apps' entrypoints do the same for their own URLs).
- ``read_only``: ``session_scope`` rolls back instead of committing (database_ui).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def normalize_pg_url(url: str) -> str:
    """Make the Postgres driver explicit so SQLAlchemy doesn't reach for psycopg2."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url  # already explicit, or sqlite — leave as-is


def build_engine(
    database_url: str,
    *,
    sqlite_fk: bool = False,
    pool_pre_ping: bool = False,
    normalize_pg: bool = False,
) -> Engine:
    """Build a SQLAlchemy engine with the requested per-app behavior."""
    url = normalize_pg_url(database_url) if normalize_pg else database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(
        url, connect_args=connect_args, pool_pre_ping=pool_pre_ping, future=True
    )
    if sqlite_fk:
        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_conn, _connection_record):
            """Enable foreign-key enforcement on SQLite connections."""
            if engine.dialect.name == "sqlite":
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    """Session factory with the shared settings used by every app."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(session_factory: sessionmaker, *, read_only: bool = False) -> Iterator[Session]:
    """Yield a Session. Commit on success unless *read_only*; roll back on error.

    read_only sessions never commit and always roll back on exit — the behavior
    database_ui relies on to guarantee it never writes.
    """
    session = session_factory()
    try:
        yield session
        if not read_only:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if read_only:
            session.rollback()
        session.close()
