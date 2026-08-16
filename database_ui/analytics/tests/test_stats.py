from datetime import datetime, timezone

from database_ui.analytics.data import ConvRow, MsgRow
from database_ui.analytics.stats import compute_stats, week_over_week


def _conv(cid, course="c1", user="a@x.edu", kind="exercise", ex="1"):
    t = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    return ConvRow(cid, course, user, ex, kind, None, "tutor_09", t, t)


def _tutor(cid, rating=0, cost=0.01, rag=False):
    return MsgRow(cid, 2, "tutor", "ok", rating, cost, '{"model":"claude-x"}', rag,
                  datetime(2026, 8, 10, 12, tzinfo=timezone.utc))


def _student(cid):
    return MsgRow(cid, 1, "student", "help", 0, None, None, False,
                  datetime(2026, 8, 10, 12, tzinfo=timezone.utc))


def test_usage_and_ratings_and_cost():
    convs = [_conv("a", user="u1@x"), _conv("b", user="u2@x")]
    msgs = [_student("a"), _tutor("a", rating=1, cost=0.02, rag=True),
            _student("b"), _tutor("b", rating=-1, cost=0.03, rag=False)]
    out = compute_stats(convs, msgs, returning={"u1@x"})
    assert out["usage"]["conversations"] == 2
    assert out["usage"]["unique_students"] == 2
    assert out["usage"]["returning_students"] == 1
    assert out["usage"]["new_students"] == 1
    assert out["ratings"]["up"] == 1 and out["ratings"]["down"] == 1
    assert out["ratings"]["positive_rate"] == 0.5
    assert round(out["cost"]["total_usd"], 2) == 0.05
    assert out["content"]["rag_turns"] == 1
    assert out["usage"]["messages_by_day"] == {"2026-08-10": 4}
    assert "c1" in out["per_course"]


def test_week_over_week_arrows():
    cur = compute_stats([_conv("a")], [_tutor("a", cost=0.10)], returning=set())
    prior = compute_stats([_conv("b"), _conv("c")], [_tutor("b"), _tutor("c")], returning=set())
    wow = week_over_week(cur, prior)
    assert wow["conversations"]["arrow"] == "▼"   # 1 < 2
    assert wow["cost_usd"]["arrow"] == "▲"          # 0.10 > ~0.01
    assert wow["unique_students"]["arrow"] == "–"   # 1 == 1, unchanged
    assert wow["new_students"]["arrow"] == "–"       # 1 == 1, unchanged
