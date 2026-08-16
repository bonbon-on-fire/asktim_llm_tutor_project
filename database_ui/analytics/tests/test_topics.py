# database_ui/analytics/tests/test_topics.py
from datetime import datetime, timezone

from database_ui.analytics.data import ConvRow
from database_ui.analytics.judge import Verdict
from database_ui.analytics.topics import aggregate_topics


def _conv(cid, course):
    t = datetime(2026, 8, 10, tzinfo=timezone.utc)
    return ConvRow(cid, course, "u@x", "1", "exercise", None, "tutor_09", t, t)


def test_topics_ranked_per_course_with_examples():
    convs = [_conv("a", "sc"), _conv("b", "sc"), _conv("c", "mol")]
    verdicts = {
        "a": Verdict(True, topics=["EOQ"], one_line=""),
        "b": Verdict(True, topics=["eoq", "safety stock"], one_line=""),
        "c": Verdict(True, topics=["ethics"], one_line=""),
    }
    firstq = {"a": "how do I find EOQ?", "b": "eoq again?", "c": "what is good?"}
    out = aggregate_topics(convs, verdicts, firstq)
    sc = out["sc"]
    assert sc[0]["topic"].lower() == "eoq" and sc[0]["count"] == 2
    assert "how do I find EOQ?" in sc[0]["examples"]
    assert set(out) == {"sc", "mol"}
