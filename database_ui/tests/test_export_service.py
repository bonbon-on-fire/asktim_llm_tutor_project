# database_ui/tests/test_export_service.py
"""Tests for the read-only export query functions."""

from __future__ import annotations

from database_ui.conftest import seed
from database_ui.services import conversations as svc


def test_list_export_filters_groups_and_sorts(db_session):
    seed(db_session)
    courses = svc.list_export_filters(db_session)

    # Two courses, sorted by display name: "MIT 21A.157 The Meaning of Life"
    # sorts before "MIT CTL.SC2x Supply Chain Design".
    keys = [c["course"] for c in courses]
    assert keys == ["meaning_of_life", "supply_chain_design"]

    sc = next(c for c in courses if c["course"] == "supply_chain_design")
    assert sc["course_name"] == "MIT CTL.SC2x Supply Chain Design"
    exercises = [a["exercise_number"] for a in sc["assignments"]]
    assert exercises == ["1", "2"]  # numeric sort
    kinds = {a["exercise_number"]: a["exercise_kind"] for a in sc["assignments"]}
    assert kinds == {"1": "exercise", "2": "practice"}
