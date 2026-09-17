"""Data check: the normalize-exercise_number migration collapses '01' -> '1'.

Runs the migration's real ``upgrade()`` against an in-memory SQLite DB seeded
with padded and bare exercise numbers, then asserts every value is normalized
and non-padded rows are left untouched.

Run:
    python -m main_ui.db.test_normalize_exercise_number_migration
"""
from __future__ import annotations

import importlib

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from main_ui.db.models import Base, Conversation

# Import the migration module by file (its name isn't a Python identifier path).
_mig = importlib.import_module(
    "main_ui.db.migrations.versions.e5a2c7d9f314_normalize_exercise_number"
)


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True

    # _normalize unit behavior.
    ok &= _check("'01' -> '1'", _mig._normalize("01") == "1")
    ok &= _check("'1' unchanged", _mig._normalize("1") == "1")
    ok &= _check("'007' -> '7'", _mig._normalize("007") == "7")
    ok &= _check("non-numeric passes through", _mig._normalize("2a") == "2a")
    ok &= _check("None passes through", _mig._normalize(None) is None)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add_all([
            Conversation(session_id="a", course="c1", exercise_number="01",
                         tutor_prompt="t"),
            Conversation(session_id="b", course="c1", exercise_number="1",
                         tutor_prompt="t"),
            Conversation(session_id="c", course="c1", exercise_number="002",
                         tutor_prompt="t"),
            Conversation(session_id="d", course="c1", exercise_number="10",
                         tutor_prompt="t"),
        ])
        s.commit()

    # Drive the real upgrade() through an Alembic op context bound to the engine.
    with engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            _mig.upgrade()

    with Session(engine) as s:
        by_session = {
            c.session_id: c.exercise_number
            for c in s.query(Conversation).all()
        }
    ok &= _check("'01' rewritten to '1'", by_session["a"] == "1", by_session["a"])
    ok &= _check("'1' left as '1'", by_session["b"] == "1", by_session["b"])
    ok &= _check("'002' rewritten to '2'", by_session["c"] == "2", by_session["c"])
    ok &= _check("'10' left as '10'", by_session["d"] == "10", by_session["d"])

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
