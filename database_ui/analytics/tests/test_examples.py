# database_ui/analytics/tests/test_examples.py
from datetime import datetime, timezone

from database_ui.analytics.data import ConvRow, MsgRow
from database_ui.analytics.judge import Verdict
from database_ui.analytics.examples import pick_examples


def _conv(cid, course):
    t = datetime(2026, 8, 10, tzinfo=timezone.utc)
    return ConvRow(cid, course, "u@x", "1", "exercise", None, "tutor_09", t, t)


def _msgs(cid, n):
    return [MsgRow(cid, i, "tutor" if i % 2 else "student", "x", 1 if i == 1 else 0,
                   0.01, None, False, datetime(2026, 8, 10, tzinfo=timezone.utc)) for i in range(n)]


def test_examples_are_deterministic_and_bucketed():
    convs = [_conv("a", "sc"), _conv("b", "sc"), _conv("c", "mol")]
    msgs = _msgs("a", 8) + _msgs("b", 2) + _msgs("c", 4)
    verdicts = {"a": Verdict(True, one_line="great"), "b": Verdict(False, one_line="bad"),
                "c": Verdict(True, one_line="ok")}
    out1 = pick_examples(convs, msgs, verdicts, seed="2026-08-09", per_course=1)
    out2 = pick_examples(convs, msgs, verdicts, seed="2026-08-09", per_course=1)
    assert out1 == out2                       # deterministic
    assert out1["high_engagement"][0] == "a"  # most messages
    assert "a" in out1["exemplary"]           # worked well + up-rated
    assert set(out1["sample"]) == {"sc", "mol"}
    assert len(out1["sample"]["sc"]) == 1
