"""SQLAlchemy engine + session factory for main_ui.

Thin wrapper over ui_core.db.session: SQLite FK enforcement on, commit-on-success
sessions. Public names (engine, SessionLocal, get_session) are unchanged.
"""

from __future__ import annotations

from ui_core.db.session import build_engine, make_session_factory, session_scope
from main_ui.config import load_config

engine = build_engine(load_config().database_url, sqlite_fk=True)
SessionLocal = make_session_factory(engine)


def get_session():
    """Yield a SQLAlchemy Session; commit on success, rollback on exception."""
    return session_scope(SessionLocal, read_only=False)
