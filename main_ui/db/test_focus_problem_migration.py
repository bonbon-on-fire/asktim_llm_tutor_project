"""Schema check: conversations.focus_problem exists and defaults to NULL.

Run:
    python -m main_ui.db.test_focus_problem_migration
"""
from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from main_ui.db.models import Base, Conversation


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    ok &= _check("column mapped", hasattr(Conversation, "focus_problem"))

    with Session(engine) as s:
        c = Conversation(
            session_id="sess", course="supply_chain_design",
            exercise_number="1", tutor_prompt="tutor_07",
        )
        s.add(c)
        s.commit()
        ok &= _check("defaults to NULL", c.focus_problem is None, c.focus_problem)

        c2 = Conversation(
            session_id="sess", course="supply_chain_design",
            exercise_number="1", tutor_prompt="tutor_07", focus_problem=2,
        )
        s.add(c2)
        s.commit()
        ok &= _check("stores an int", c2.focus_problem == 2, c2.focus_problem)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
