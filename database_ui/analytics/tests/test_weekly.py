# database_ui/analytics/tests/test_weekly.py
from datetime import date, datetime, timezone

import pytest

from database_ui.analytics import cache as cache_mod
from database_ui.analytics import weekly
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
