# database_ui/analytics/tests/test_weekly.py
from datetime import date, datetime, timezone

import pytest

from database_ui.analytics import cache as cache_mod
from database_ui.analytics import weekly
from database_ui.analytics.data import fetch_conversations
from database_ui.analytics.judge import FakeJudge, Verdict
from database_ui.analytics.weeks import week_containing
from database_ui.conftest import seed
from database_ui.db.session import SessionLocal


@pytest.fixture()
def session():
    s = SessionLocal()
    seed(s)
    yield s
    s.close()


def test_run_week_writes_cache_and_report(tmp_path, monkeypatch, session):
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    wk = week_containing(date(2026, 5, 1))     # seeded rows are dated May 1, 2026
    judge = FakeJudge(default=Verdict(False, issues=[
        {"type": "gave_away_answer", "severity": "high", "quote": "q"}], topics=["EOQ"], one_line="bad"))
    path, md = weekly.run_week(
        session, wk, judge, judge_model="fake",
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
    )
    assert path.exists() and path.name.endswith(".json")
    blob = cache_mod.read_cache(wk.key)
    assert blob["judged_count"] >= 1
    assert "Weekly report" in md
    # report.md written beside the cache
    assert (tmp_path / "report.md").exists()


def test_run_week_reuses_verdict_when_hash_matches(tmp_path, monkeypatch, session):
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    wk = week_containing(date(2026, 5, 1))     # seeded rows are dated May 1, 2026

    # The one seeded conversation with an actual (non-empty) transcript, so its
    # transcript hash is unambiguous.
    convs = fetch_conversations(session, wk, None)
    sc_id = next(
        c.id for c in convs
        if c.course == "supply_chain_design" and c.exercise_number == "1"
    )

    judge1 = FakeJudge(default=Verdict(True, one_line="FIRST-JUDGE"))
    weekly.run_week(
        session, wk, judge1, judge_model="fake1",
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
    )
    blob = cache_mod.read_cache(wk.key)
    assert blob["conversations"][sc_id]["one_line"] == "FIRST-JUDGE"
    assert blob["_hashes"][sc_id]  # correct hash was recorded

    # Second run: unchanged transcript -> reuse the first judge's verdict, even
    # though a different (distinguishable) judge is passed in.
    judge2 = FakeJudge(default=Verdict(True, one_line="SECOND-JUDGE"))
    weekly.run_week(
        session, wk, judge2, judge_model="fake2",
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        prior_cache=blob,
    )
    blob2 = cache_mod.read_cache(wk.key)
    assert blob2["conversations"][sc_id]["one_line"] == "FIRST-JUDGE"

    # Mismatch path: a stale/incorrect hash forces the new judge to be consulted.
    stale_blob = dict(blob)
    stale_blob["_hashes"] = dict(blob["_hashes"])
    stale_blob["_hashes"][sc_id] = "stale"
    weekly.run_week(
        session, wk, judge2, judge_model="fake2",
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
        prior_cache=stale_blob,
    )
    blob3 = cache_mod.read_cache(wk.key)
    assert blob3["conversations"][sc_id]["one_line"] == "SECOND-JUDGE"


class _RaisesOnceJudge:
    """Judge that raises on the first conversation and succeeds afterwards —
    stands in for an empty-transcript JudgeError or a one-off LLM 529."""

    def __init__(self):
        self._calls = 0

    def judge(self, course, transcript, *, exercise=""):
        self._calls += 1
        if self._calls == 1:
            raise RuntimeError("boom: e.g. LLM 529 or empty-transcript JudgeError")
        return Verdict(True, one_line="ok")


def test_run_week_isolates_one_failing_conversation(tmp_path, monkeypatch, session):
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    wk = week_containing(date(2026, 5, 1))
    convs = fetch_conversations(session, wk, None)
    assert len(convs) >= 2  # need one to fail and at least one to succeed

    path, md = weekly.run_week(
        session, wk, _RaisesOnceJudge(), judge_model="fake",
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
    )

    # One conversation failed, but the job still shipped a cache + report.
    assert path.exists()
    assert "Weekly report" in md
    blob = cache_mod.read_cache(wk.key)
    assert blob["skipped"] == 1
    # The failed conversation is absent; every other conversation was stored.
    assert len(blob["conversations"]) == len(convs) - 1
    # Its hash was dropped so a later run retries it rather than reusing nothing.
    assert len(blob["_hashes"]) == len(convs) - 1


def test_run_week_preserves_grade_across_reuse(tmp_path, monkeypatch, session):
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    wk = week_containing(date(2026, 5, 1))
    convs = fetch_conversations(session, wk, None)
    sc_id = next(
        c.id for c in convs
        if c.course == "supply_chain_design" and c.exercise_number == "1"
    )
    grade = {"total_score": 33, "max_score": 40, "overview": "solid"}

    # First run: the verdict carries a full grade -> it must land in the cache.
    judge1 = FakeJudge(default=Verdict(True, one_line="J1", grade=grade))
    weekly.run_week(session, wk, judge1, judge_model="fake1",
                    generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc))
    blob = cache_mod.read_cache(wk.key)
    assert blob["conversations"][sc_id]["grade"] == grade

    # Second run: unchanged transcript -> verdict reused; the grade must survive
    # even though the new judge would produce none.
    judge2 = FakeJudge(default=Verdict(True, one_line="J2"))
    weekly.run_week(session, wk, judge2, judge_model="fake2",
                    generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc), prior_cache=blob)
    blob2 = cache_mod.read_cache(wk.key)
    assert blob2["conversations"][sc_id]["grade"] == grade
