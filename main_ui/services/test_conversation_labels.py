"""Standalone test: main_ui sidebar summaries carry a per-course label template.

Each conversation is labelled by its OWN course, so a mixed-course history
renders every row in the format its course defines.

Run:
    python -m main_ui.services.test_conversation_labels
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
        # A course with a ui_labels.json override.
        scd = svc.find_or_create_conversation(
            s, session_id="a", conversation_id=None, course="supply_chain_design",
            exercise_number="7", exercise_kind="practice", tutor_prompt="tutor_07",
        )
        # A course without one -> defaults.
        ccc = svc.find_or_create_conversation(
            s, session_id="b", conversation_id=None, course="cities_and_climate_change",
            exercise_number="7", exercise_kind="practice", tutor_prompt="tutor_07",
        )
        scd_ex = svc.find_or_create_conversation(
            s, session_id="c", conversation_id=None, course="supply_chain_design",
            exercise_number="3", exercise_kind="exercise", tutor_prompt="tutor_07",
        )
        # A course without any override -> default exercise label.
        ccc_ex = svc.find_or_create_conversation(
            s, session_id="d", conversation_id=None, course="cities_and_climate_change",
            exercise_number="3", exercise_kind="exercise", tutor_prompt="tutor_07",
        )
        s.commit()

        ok &= _check(
            "supply_chain_design practice -> Week template",
            svc._summarize_extra(scd)["label_template"] == "Week {n} Practice",
            svc._summarize_extra(scd),
        )
        ok &= _check(
            "other course practice -> default template",
            svc._summarize_extra(ccc)["label_template"] == "Practice {n}",
            svc._summarize_extra(ccc),
        )
        ok &= _check(
            "supply_chain_design exercise -> Week Graded template",
            svc._summarize_extra(scd_ex)["label_template"] == "Week {n} Graded",
            svc._summarize_extra(scd_ex),
        )
        ok &= _check(
            "other course exercise -> default template",
            svc._summarize_extra(ccc_ex)["label_template"] == "Exercise {n}",
            svc._summarize_extra(ccc_ex),
        )
        ok &= _check(
            "exercise_kind still present",
            svc._summarize_extra(scd)["exercise_kind"] == "practice",
            svc._summarize_extra(scd),
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
