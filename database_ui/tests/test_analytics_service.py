# database_ui/tests/test_analytics_service.py
from datetime import date

import pytest

from database_ui.analytics import cache as cache_mod
from database_ui.analytics.weeks import week_containing
from database_ui.conftest import seed
from database_ui.db.session import SessionLocal
from database_ui.services import analytics as svc


@pytest.fixture()
def session():
    s = SessionLocal()
    seed(s)
    yield s
    s.close()


def test_live_stats_scoped(session):
    wk = week_containing(date(2026, 5, 1))   # seeded rows are dated May 1, 2026
    allc = svc.live_stats(session, wk, None)
    scoped = svc.live_stats(session, wk, ["supply_chain_design"])
    assert allc["usage"]["conversations"] >= scoped["usage"]["conversations"]
    assert set(scoped["per_course"]) <= {"supply_chain_design"}


def test_cached_sections_filters_and_strips_hashes(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    (tmp_path / "2026-05-03.json").write_text(
        '{"version":1,"week_start":"2026-05-03","conversations":'
        '{"u1":{"course":"supply_chain_design","worked_well":true,"issues":[],"topics":[],"one_line":""},'
        '"u2":{"course":"meaning_of_life","worked_well":true,"issues":[],"topics":[],"one_line":""}},'
        '"examples":{"exemplary":[],"high_engagement":[],"sample":{}},'
        '"topics_by_course":{},"_hashes":{"u1":"x"}}', encoding="utf-8")
    out = svc.cached_sections("2026-05-03", ["supply_chain_design"])
    assert set(out["conversations"]) == {"u1"}
    assert "_hashes" not in out


def test_cached_sections_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    assert svc.cached_sections("1999-01-03", None) is None
