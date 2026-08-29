# database_ui/analytics/tests/test_review.py
from datetime import datetime, timezone

from database_ui.analytics.data import ConvRow
from database_ui.analytics.judge import Verdict
from database_ui.analytics.review import build_reviews, course_material, practice_label


def _conv(cid, course, number="1", kind="exercise"):
    t = datetime(2026, 8, 10, tzinfo=timezone.utc)
    return ConvRow(cid, course, "u@x", number, kind, None, "tutor_09", t, t)


def test_practice_label_matches_dashboard_wording():
    assert practice_label("practice", "7") == "Practice 7"
    assert practice_label("exercise", "3") == "Exercise 3"
    # A blank/None number has no content week to attribute to.
    assert practice_label("practice", "") == "Unspecified"
    assert practice_label("exercise", None) == "Unspecified"


def test_course_material_groups_by_course_and_practice():
    convs = [
        _conv("a", "sc", "7", "practice"),
        _conv("b", "sc", "7", "practice"),
        _conv("c", "sc", "8", "practice"),
        _conv("d", "mol", "3", "exercise"),
    ]
    verdicts = {
        "a": Verdict(True, topics=["EOQ"], one_line="great EOQ walk-through"),
        "b": Verdict(False, topics=["eoq", "safety stock"], one_line="gave it away"),
        "c": Verdict(True, topics=["newsvendor"], one_line="solid newsvendor"),
        "d": Verdict(True, topics=["ethics"], one_line="thoughtful"),
    }
    firstq = {"a": "how do I find EOQ?", "b": "eoq again?", "c": "newsvendor?", "d": "what is good?"}
    mat = course_material(convs, verdicts, firstq)

    assert set(mat) == {"sc", "mol"}
    # Within a course, material is split by content week (Practice #).
    assert set(mat["sc"]) == {"Practice 7", "Practice 8"}
    assert set(mat["mol"]) == {"Exercise 3"}
    # Topics de-duplicate case-insensitively within one (course, practice), order kept.
    assert mat["sc"]["Practice 7"]["topics"] == ["EOQ", "safety stock"]
    assert mat["sc"]["Practice 7"]["questions"] == ["how do I find EOQ?", "eoq again?"]
    assert "great EOQ walk-through" in mat["sc"]["Practice 7"]["overviews"]
    # Practice 8's material stays separate from Practice 7's.
    assert mat["sc"]["Practice 8"]["topics"] == ["newsvendor"]


def test_course_material_orders_practices_numerically_unspecified_last():
    convs = [
        _conv("a", "sc", "10", "practice"),
        _conv("b", "sc", "2", "practice"),
        _conv("c", "sc", "", "practice"),   # no number -> Unspecified bucket
    ]
    verdicts = {
        "a": Verdict(True, topics=["t10"], one_line="x"),
        "b": Verdict(True, topics=["t2"], one_line="y"),
        "c": Verdict(True, topics=["t0"], one_line="z"),
    }
    firstq = {"a": "q", "b": "q", "c": "q"}
    mat = course_material(convs, verdicts, firstq)
    # 2 before 10 (numeric, not lexical); the Unspecified bucket sorts last.
    assert list(mat["sc"]) == ["Practice 2", "Practice 10", "Unspecified"]


def test_build_reviews_one_paragraph_per_practice_via_fake():
    material = {
        "sc": {
            "Practice 7": {"questions": ["q7"], "overviews": ["ok"], "topics": ["EOQ"]},
            "Practice 8": {"questions": ["q8"], "overviews": ["ok"], "topics": ["newsvendor"]},
        },
        "mol": {
            "Exercise 3": {"questions": [], "overviews": [], "topics": ["ethics"]},
        },
    }
    seen = []

    def fake(course, label, mat, model):
        seen.append((course, label, model))
        return f"{course}/{label}: {', '.join(mat['topics'])}."

    out = build_reviews(material, model="fake-model", review_fn=fake)
    # Each course maps to an ordered list of {label, text} sections, one per practice.
    assert [s["label"] for s in out["sc"]] == ["Practice 7", "Practice 8"]
    assert out["sc"][0]["text"].startswith("sc/Practice 7: EOQ")
    assert out["mol"][0]["label"] == "Exercise 3"
    assert ("sc", "Practice 7", "fake-model") in seen


def test_build_reviews_skips_empty_and_failing_practices():
    material = {
        "sc": {
            "Practice 7": {"questions": [], "overviews": [], "topics": []},   # no material
            "Practice 8": {"questions": ["q"], "overviews": [], "topics": ["t"]},  # boom
        },
        "mol": {
            "Exercise 3": {"questions": ["q"], "overviews": [], "topics": ["t"]},  # ok
        },
    }

    def fake(course, label, mat, model):
        if label == "Practice 8":
            raise RuntimeError("LLM 529")
        return "fine"

    out = build_reviews(material, review_fn=fake)
    # Practice 7 is never sent (no material); Practice 8 fails; sc has no surviving
    # section and is dropped entirely. Only mol/Exercise 3 survives.
    assert set(out) == {"mol"}
    assert [s["label"] for s in out["mol"]] == ["Exercise 3"]
