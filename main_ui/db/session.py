"""SQLAlchemy engine + session factory for main_ui.

Build the engine lazily from `config.database_url`. For SQLite, enable FK
enforcement on every new connection (off by default). For Postgres, use a
standard pool with no special connect args.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from main_ui.config import load_config


def _build_engine() -> Engine:
    config = load_config()
    url = config.database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args, future=True)


engine: Engine = _build_engine()


@event.listens_for(engine, "connect")
def _enable_sqlite_fk(dbapi_conn, _connection_record):
    """Enable foreign-key enforcement on SQLite connections."""
    if engine.dialect.name == "sqlite":
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def get_session() -> Iterator[Session]:
    """Yield a SQLAlchemy Session; commit on success, rollback on exception."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
