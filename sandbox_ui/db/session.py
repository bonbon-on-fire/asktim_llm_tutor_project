"""SQLAlchemy engine + session factory for sandbox_ui.

Thin wrapper over ui_core.db.session (same behavior as main_ui: SQLite FK on,
commit-on-success). Public names unchanged.
"""

from __future__ import annotations

from ui_core.db.session import build_engine, make_session_factory, session_scope
from sandbox_ui.config import load_config

engine = build_engine(load_config().database_url, sqlite_fk=True)
SessionLocal = make_session_factory(engine)


def get_session():
    """Yield a SQLAlchemy Session; commit on success, rollback on exception."""
    return session_scope(SessionLocal, read_only=False)
