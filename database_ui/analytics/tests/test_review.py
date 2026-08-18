# database_ui/analytics/tests/test_review.py
from datetime import datetime, timezone

from database_ui.analytics.data import ConvRow
from database_ui.analytics.judge import Verdict
from database_ui.analytics.review import build_reviews, course_material


def _conv(cid, course):
    t = datetime(2026, 8, 10, tzinfo=timezone.utc)
    return ConvRow(cid, course, "u@x", "1", "exercise", None, "tutor_09", t, t)


def test_course_material_groups_and_dedupes_topics():
    convs = [_conv("a", "sc"), _conv("b", "sc"), _conv("c", "mol")]
    verdicts = {
        "a": Verdict(True, topics=["EOQ"], one_line="great EOQ walk-through"),
        "b": Verdict(False, topics=["eoq", "safety stock"], one_line="gave it away"),
        "c": Verdict(True, topics=["ethics"], one_line="solid"),
    }
    firstq = {"a": "how do I find EOQ?", "b": "eoq again?", "c": "what is good?"}
    mat = course_material(convs, verdicts, firstq)

    assert set(mat) == {"sc", "mol"}
    # Topics are de-duplicated case-insensitively within a course, order kept.
    assert mat["sc"]["topics"] == ["EOQ", "safety stock"]
    assert mat["sc"]["questions"] == ["how do I find EOQ?", "eoq again?"]
    assert "great EOQ walk-through" in mat["sc"]["overviews"]


def test_build_reviews_one_paragraph_per_course_via_fake():
    material = {
        "sc": {"questions": ["how do I find EOQ?"], "overviews": ["ok"], "topics": ["EOQ"]},
        "mol": {"questions": [], "overviews": [], "topics": ["ethics"]},
    }
    seen = []

    def fake(course, mat, model):
        seen.append((course, model))
        return f"Students in {course} focused on {', '.join(mat['topics'])}."

    out = build_reviews(material, model="fake-model", review_fn=fake)
    assert out["sc"].startswith("Students in sc focused on EOQ")
    assert out["mol"].startswith("Students in mol focused on ethics")
    assert ("sc", "fake-model") in seen


def test_build_reviews_skips_empty_and_failing_courses():
    material = {
        "empty": {"questions": [], "overviews": [], "topics": []},
        "boom": {"questions": ["q"], "overviews": [], "topics": []},
        "ok": {"questions": ["q"], "overviews": [], "topics": ["t"]},
    }

    def fake(course, mat, model):
        if course == "boom":
            raise RuntimeError("LLM 529")
        return "fine"

    out = build_reviews(material, review_fn=fake)
    # "empty" is never sent (no material); "boom" fails and is dropped; only "ok" survives.
    assert set(out) == {"ok"}
