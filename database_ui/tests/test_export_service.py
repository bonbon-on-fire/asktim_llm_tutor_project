# database_ui/tests/test_export_service.py
"""Tests for the read-only export query functions."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from database_ui.conftest import seed
from database_ui.db.models import Conversation, Message
from database_ui.services import conversations as svc


def _add_padded_duplicate(session):
    """Add a conversation for supply_chain_design stored with a padded '01'.

    Mimics a record written before the write-path normalization fix: same
    assignment as the seeded "1", but stored with a zero-padded number. Returns
    the conversation id and adds one student message so it yields an export row.
    """
    dt = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    conv = Conversation(
        id=uuid.uuid4(), session_id="s-pad", username="stu@mit.edu",
        course="supply_chain_design", exercise_number="01", exercise_kind="exercise",
        focus_problem=None, tutor_prompt="p", started_at=dt, last_active_at=dt,
    )
    session.add(conv)
    session.flush()
    session.add(Message(
        conversation_id=conv.id, turn=1, role="student", content="padded",
        pedagogical_reasoning=None, rating=0, cost_usd=None, usage_json=None,
        retrieved_context=None, created_at=dt,
    ))
    session.commit()
    return conv.id


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


def test_iter_export_rows_filters_and_columns(db_session):
    ids = seed(db_session)
    # Only supply_chain_design exercise "1" (the 2-message conversation).
    rows = list(svc.iter_export_rows(db_session, {("supply_chain_design", "1")}))

    assert len(rows) == 2
    # Every row has exactly the declared columns.
    for row in rows:
        assert set(row.keys()) == set(svc.EXPORT_COLUMNS)
    # Ordered by turn then id: student turn first, tutor second.
    assert [r["role"] for r in rows] == ["student", "tutor"]

    student, tutor = rows
    assert student["conversation_id"] == str(ids["sc_id"])
    assert student["course_name"] == "MIT CTL.SC2x Supply Chain Design"
    assert student["image_count"] == 1
    assert student["file_count"] == 1  # one CSV attachment on the student turn
    assert tutor["image_count"] == 0
    assert tutor["file_count"] == 0
    assert tutor["rating"] == 1
    assert tutor["model"] == "gpt-5.4-2026-03-05"  # parsed from usage_json
    assert tutor["cost_usd"] == 0.0123
    assert tutor["usage_json"].startswith("{")
    assert tutor["retrieved_context"].startswith("[")


def test_iter_export_rows_multiple_pairs_excludes_others(db_session):
    seed(db_session)
    pairs = {("supply_chain_design", "2"), ("meaning_of_life", "1")}
    rows = list(svc.iter_export_rows(db_session, pairs))
    # sc2 and mol conversations have no messages seeded -> zero rows, and the
    # 2-message sc/"1" conversation is NOT in the selection so it's excluded.
    assert rows == []


def test_iter_export_rows_empty_pairs_yields_nothing(db_session):
    seed(db_session)
    assert list(svc.iter_export_rows(db_session, set())) == []


def test_list_export_filters_collapses_padded_duplicate(db_session):
    seed(db_session)
    _add_padded_duplicate(db_session)  # supply_chain_design "01"
    courses = svc.list_export_filters(db_session)

    sc = next(c for c in courses if c["course"] == "supply_chain_design")
    exercises = [a["exercise_number"] for a in sc["assignments"]]
    # "01" collapses into the single normalized "1" option — no duplicate entry.
    assert exercises == ["1", "2"]


def test_iter_export_rows_pulls_padded_variant(db_session):
    seed(db_session)
    _add_padded_duplicate(db_session)  # padded "01" conversation, 1 message
    # Requesting the normalized "1" must also pull the padded "01" rows: the
    # seeded 2-message conversation plus the padded conversation's 1 message.
    rows = list(svc.iter_export_rows(db_session, {("supply_chain_design", "1")}))
    assert len(rows) == 3
    assert any(r["content"] == "padded" for r in rows)
