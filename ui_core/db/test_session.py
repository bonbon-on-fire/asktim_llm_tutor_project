"""Standalone tests for ui_core.db.session (no pytest).

Run with:
    python -m ui_core.db.test_session
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy import Column, Integer, text
from sqlalchemy.orm import declarative_base

from ui_core.db.session import (
    normalize_pg_url,
    build_engine,
    make_session_factory,
    session_scope,
)

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    """Record and print a PASS/FAIL for *name* based on *condition*."""
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def test_normalize_pg_url() -> None:
    """Check ``normalize_pg_url`` rewrites Postgres URLs to the psycopg driver and leaves others alone."""
    _check("postgres:// -> psycopg", normalize_pg_url("postgres://u@h/db") == "postgresql+psycopg://u@h/db")
    _check("postgresql:// -> psycopg", normalize_pg_url("postgresql://u@h/db") == "postgresql+psycopg://u@h/db")
    _check("already explicit unchanged", normalize_pg_url("postgresql+psycopg://u@h/db") == "postgresql+psycopg://u@h/db")
    _check("sqlite unchanged", normalize_pg_url("sqlite:///x.db") == "sqlite:///x.db")


def test_build_engine_sqlite_fk_enforced() -> None:
    """Check ``build_engine``'s ``sqlite_fk`` flag toggles the SQLite ``foreign_keys`` PRAGMA."""
    Base = declarative_base()

    class Parent(Base):
        __tablename__ = "parent"
        id = Column(Integer, primary_key=True)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        url = f"sqlite:///{Path(tmp) / 'fk.db'}"
        eng_on = build_engine(url, sqlite_fk=True)
        Base.metadata.create_all(eng_on)
        with eng_on.connect() as conn:
            fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
        eng_on.dispose()
        _check("sqlite_fk=True turns PRAGMA foreign_keys on", fk == 1, f"got {fk}")

        url2 = f"sqlite:///{Path(tmp) / 'nofk.db'}"
        eng_off = build_engine(url2, sqlite_fk=False)
        with eng_off.connect() as conn:
            fk_off = conn.execute(text("PRAGMA foreign_keys")).scalar()
        eng_off.dispose()
        _check("sqlite_fk=False leaves PRAGMA off", fk_off == 0, f"got {fk_off}")


def test_session_scope_commit_vs_readonly() -> None:
    """Check ``session_scope`` commits by default and rolls back when ``read_only=True``."""
    Base = declarative_base()

    class Row(Base):
        __tablename__ = "row"
        id = Column(Integer, primary_key=True)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        url = f"sqlite:///{Path(tmp) / 'scope.db'}"
        engine = build_engine(url)
        Base.metadata.create_all(engine)
        factory = make_session_factory(engine)

        with session_scope(factory) as s:      # read_only=False -> commits
            s.add(Row(id=1))
        with session_scope(factory) as s:
            persisted = s.get(Row, 1) is not None
        _check("non-read-only scope commits", persisted)

        with session_scope(factory, read_only=True) as s:   # rolls back
            s.add(Row(id=2))
        with session_scope(factory) as s:
            rolled_back = s.get(Row, 2) is None
        _check("read_only scope rolls back", rolled_back)
        engine.dispose()


def main() -> int:
    """Run all tests in this module and return an exit code (1 if any failed)."""
    for t in (test_normalize_pg_url, test_build_engine_sqlite_fk_enforced, test_session_scope_commit_vs_readonly):
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
