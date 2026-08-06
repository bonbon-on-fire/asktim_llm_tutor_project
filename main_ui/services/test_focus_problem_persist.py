"""find_or_create_conversation persists focus_problem on new rows only.

Run:
    python -m main_ui.services.test_focus_problem_persist
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from main_ui.db.models import Base
from main_ui.services.conversation import find_or_create_conversation


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        convo = find_or_create_conversation(
            db, session_id="sess", conversation_id=None,
            course="supply_chain_design", exercise_number="1",
            tutor_prompt="tutor_07", exercise_kind="practice", focus_problem=2,
        )
        db.commit()
        ok &= _check("new convo stores focus", convo.focus_problem == 2, convo.focus_problem)

        # Continuation: a differing request focus must NOT overwrite the stored value.
        again = find_or_create_conversation(
            db, session_id="sess", conversation_id=convo.id,
            course="supply_chain_design", exercise_number="1",
            tutor_prompt="tutor_07", exercise_kind="practice", focus_problem=7,
        )
        ok &= _check("continuation keeps stored focus", again.focus_problem == 2, again.focus_problem)

        # No focus -> NULL.
        nofocus = find_or_create_conversation(
            db, session_id="sess2", conversation_id=None,
            course="supply_chain_design", exercise_number="1", tutor_prompt="tutor_07",
        )
        db.commit()
        ok &= _check("absent focus -> NULL", nofocus.focus_problem is None, nofocus.focus_problem)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
