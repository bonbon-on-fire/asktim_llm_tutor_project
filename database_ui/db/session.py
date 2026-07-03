"""SQLAlchemy engine + session factory for database_ui (read-only).

Thin wrapper over web_core.db.session: normalizes Railway/Heroku postgres URLs to
psycopg3, uses pool_pre_ping for a long-lived remote DB, and a read-only session
that always rolls back (this app never writes). Public names unchanged.
"""

from __future__ import annotations

from web_core.db.session import build_engine, make_session_factory, session_scope
from database_ui.config import load_config

engine = build_engine(
    load_config().database_url, pool_pre_ping=True, normalize_pg=True
)
SessionLocal = make_session_factory(engine)


def get_session():
    """Yield a read-only Session; always rolls back (this app never writes)."""
    return session_scope(SessionLocal, read_only=True)
