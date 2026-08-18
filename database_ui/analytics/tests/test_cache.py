# database_ui/analytics/tests/test_cache.py
from datetime import datetime, timezone

from database_ui.analytics import cache as c
from database_ui.analytics.weeks import Week


def _blob():
    return {
        "version": c.CACHE_VERSION,
        "week_start": "2026-08-09", "week_end": "2026-08-15", "tz": "America/New_York",
        "generated_at": "2026-08-17T05:12:00-04:00",
        "judge_model": "claude-sonnet-5", "judged_count": 2, "skipped": 0,
        "conversations": {
            "u1": {"course": "supply_chain_design", "worked_well": False,
                   "issues": [{"type": "gave_away_answer", "severity": "high", "quote": "..."}],
                   "topics": ["EOQ"], "one_line": "gave answer"},
            "u2": {"course": "meaning_of_life", "worked_well": True,
                   "issues": [], "topics": ["ethics"], "one_line": "good"},
        },
        "examples": {"exemplary": ["u2"], "high_engagement": ["u1"],
                     "sample": {"supply_chain_design": ["u1"], "meaning_of_life": ["u2"]}},
        "topics_by_course": {
            "supply_chain_design": [{"topic": "EOQ", "count": 1, "examples": ["how?"]}],
            "meaning_of_life": [{"topic": "ethics", "count": 1, "examples": ["why?"]}],
        },
        "ai_review_by_course": {
            "supply_chain_design": "Students worked on EOQ.",
            "meaning_of_life": "Students debated ethics.",
        },
    }


def test_filter_cache_drops_out_of_scope():
    filtered = c.filter_cache(_blob(), ["supply_chain_design"])
    assert set(filtered["conversations"]) == {"u1"}
    assert filtered["examples"]["exemplary"] == []      # u2 is out of scope
    assert filtered["examples"]["high_engagement"] == ["u1"]
    assert set(filtered["examples"]["sample"]) == {"supply_chain_design"}
    assert set(filtered["topics_by_course"]) == {"supply_chain_design"}
    # The AI review is scoped the same way: a course login sees only its own.
    assert set(filtered["ai_review_by_course"]) == {"supply_chain_design"}


def test_filter_cache_master_is_identity():
    assert c.filter_cache(_blob(), None)["conversations"].keys() == _blob()["conversations"].keys()


def test_write_then_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "CACHE_DIR", tmp_path)
    wk = Week.__call__(__import__("datetime").date(2026, 8, 9))
    path = c.write_cache(
        wk,
        judged={"u1": {"course": "c1", "worked_well": True, "issues": [], "topics": [], "one_line": "ok"}},
        examples={"exemplary": ["u1"], "high_engagement": [], "sample": {"c1": ["u1"]}},
        topics_by_course={"c1": [{"topic": "t", "count": 1, "examples": []}]},
        judge_model="claude-sonnet-5",
        generated_at=datetime(2026, 8, 17, 9, tzinfo=timezone.utc),
        judged_count=1, skipped=0,
        ai_review_by_course={"c1": "Students worked on t."},
    )
    assert path.name == "2026-08-09.json"
    blob = c.read_cache("2026-08-09")
    assert blob["week_start"] == "2026-08-09" and blob["judged_count"] == 1
    assert blob["ai_review_by_course"] == {"c1": "Students worked on t."}
    assert "2026-08-09" in c.available_weeks()
