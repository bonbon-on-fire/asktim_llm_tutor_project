"""Standalone test: main_ui find_or_create_conversation persists exercise_kind.

Run:
    python -m main_ui.services.test_conversation_practice
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from main_ui.db.models import Base
from main_ui.services import conversation as svc


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    ok = True
    with Session(engine) as s:
        convo = svc.find_or_create_conversation(
            s, session_id="sess", conversation_id=None, course="c",
            exercise_number="7", exercise_kind="practice", tutor_prompt="tutor_07",
        )
        s.commit()
        ok &= _check("persists practice kind", convo.exercise_kind == "practice", convo.exercise_kind)

        convo2 = svc.find_or_create_conversation(
            s, session_id="sess2", conversation_id=None, course="c",
            exercise_number="3", tutor_prompt="tutor_07",
        )
        s.commit()
        ok &= _check("defaults to exercise", convo2.exercise_kind == "exercise", convo2.exercise_kind)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
