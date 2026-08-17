# database_ui/analytics/tests/test_flags.py
from datetime import datetime, timezone

from database_ui.analytics.data import ConvRow, MsgRow
from database_ui.analytics.judge import Verdict
from database_ui.analytics.flags import build_flags


def _conv(cid, course="sc", ex="1"):
    t = datetime(2026, 8, 10, tzinfo=timezone.utc)
    return ConvRow(cid, course, "u@x", ex, "exercise", None, "tutor_09", t, t)


def _tutor(cid, rating):
    return MsgRow(cid, 2, "tutor", "text", rating, 0.01, None, False,
                  datetime(2026, 8, 10, tzinfo=timezone.utc))


def test_flags_union_and_overlap():
    convs = [_conv("a"), _conv("b"), _conv("c")]
    msgs = [_tutor("a", -1), _tutor("b", 0), _tutor("c", -1)]
    verdicts = {
        "a": Verdict(False, issues=[{"type": "gave_away_answer", "severity": "high", "quote": "x"}], one_line="bad"),
        "b": Verdict(False, issues=[{"type": "factual_error", "severity": "medium", "quote": "y"}], one_line="err"),
        "c": Verdict(True, one_line="ok"),
    }
    out = build_flags(convs, msgs, verdicts)
    ids = {i["id"] for i in out["items"]}
    assert ids == {"a", "b", "c"}          # a: both, b: judge only, c: thumb only
    assert out["thumbs_down"] == 2 and out["judge_flagged"] == 2 and out["overlap"] == 1
    assert out["items"][0]["id"] == "a"    # high severity + both sources ranks first


def test_flags_expose_score_and_average():
    convs = [_conv("a"), _conv("b")]
    msgs = [_tutor("a", -1), _tutor("b", 0)]
    verdicts = {
        "a": Verdict(False, issues=[{"type": "1.1.A.a", "severity": "high", "quote": "x"}],
                     one_line="bad", grade={"total_score": 20, "max_score": 40}),
        "b": Verdict(True, one_line="ok", grade={"total_score": 36, "max_score": 40}),
    }
    out = build_flags(convs, msgs, verdicts)
    # Only "a" is flagged (b worked well, no thumb); its score comes from the grade.
    item_a = next(i for i in out["items"] if i["id"] == "a")
    assert item_a["score"] == 20
    # Average is over ALL graded verdicts (a and b), not only flagged ones.
    assert out["avg_score"] == {"avg": 28.0, "max": 40, "n": 2}
