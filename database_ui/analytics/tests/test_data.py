# database_ui/analytics/tests/test_data.py
from datetime import datetime, timezone

import pytest

from database_ui.analytics import data as d
from database_ui.analytics.weeks import week_containing
from database_ui.conftest import seed
from database_ui.db.session import SessionLocal


@pytest.fixture()
def session():
    s = SessionLocal()
    ids = seed(s)          # seeds convos dated 2026-05-<day> 12:00 UTC
    yield s, ids
    s.close()


def _seed_week():
    # Seed rows are all dated Fri May 1, 2026 -> the Sun Apr 26 - Sat May 2 week.
    return week_containing(datetime(2026, 5, 1).date())


def test_fetch_conversations_windows_and_scopes(session):
    s, ids = session
    wk = _seed_week()
    # A distant week returns nothing.
    far = week_containing(datetime(2026, 1, 5).date())
    assert d.fetch_conversations(s, far, None) == []
    # Scope to one course -> only that course's rows come back.
    scoped = d.fetch_conversations(s, wk, ["supply_chain_design"])
    assert scoped, "expected seeded SC conversations in-window"
    assert {c.course for c in scoped} == {"supply_chain_design"}


def test_fetch_messages_maps_rag_flag_and_rating(session):
    s, ids = session
    rows = d.fetch_messages(s, [str(ids["sc_id"])])
    tutor = [m for m in rows if m.role == "tutor"]  # seed uses role="tutor"
    assert any(m.rating == 1 for m in tutor)
    assert any(m.has_rag for m in tutor)  # seeded tutor msg has retrieved_context


def test_prior_usernames(session):
    s, ids = session
    later = datetime(2026, 6, 1, tzinfo=timezone.utc)
    names = d.prior_usernames(s, later, None)
    assert isinstance(names, set)


def test_fetch_transcript_is_ordered(session):
    s, ids = session
    pairs = d.fetch_transcript(s, str(ids["sc_id"]))
    assert len(pairs) >= 2
    assert pairs[0][0] == "student"   # student turn precedes tutor turn
    assert pairs[-1][0] == "tutor"
