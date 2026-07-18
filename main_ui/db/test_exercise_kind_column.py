"""Standalone test: main_ui Conversation has exercise_kind defaulting to 'exercise'.

Run:
    python -m main_ui.db.test_exercise_kind_column
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from main_ui.db.models import Base, Conversation


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    ok = True
    with Session(engine) as s:
        c = Conversation(
            session_id="sess", course="c", exercise_number="1", tutor_prompt="tutor_07"
        )
        s.add(c)
        s.commit()
        ok &= _check("defaults to exercise", c.exercise_kind == "exercise", c.exercise_kind)
        c2 = Conversation(
            session_id="s2", course="c", exercise_number="7",
            tutor_prompt="tutor_07", exercise_kind="practice",
        )
        s.add(c2)
        s.commit()
        ok &= _check("stores practice", c2.exercise_kind == "practice", c2.exercise_kind)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
