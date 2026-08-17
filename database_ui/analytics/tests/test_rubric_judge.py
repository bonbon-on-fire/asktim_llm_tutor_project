"""RubricJudge adapter: grade→Verdict mapping, transcript pairing, injection seams.
No network: the real Anthropic calls are replaced by injected grade_fn/topics_fn."""
from database_ui.analytics.rubric_judge import (
    SCORE_THRESHOLD,
    DEFAULT_JUDGE_MODEL,
    RubricJudge,
    pairs_to_exchanges,
    grade_to_verdict,
)


def _grade(total, deductions=None):
    """A minimal grade payload with one criterion carrying the given deductions."""
    return {
        "total_score": total,
        "max_score": 40,
        "overview": "Solid Socratic guidance." if total >= SCORE_THRESHOLD else "Handed over the answer.",
        "sections": {
            "1_pedagogy": {
                "criteria": {"1.1": {"deductions": deductions or [], "score": 0, "max": 12}},
            }
        },
    }


def test_pairs_to_exchanges_pairs_student_then_tutor():
    transcript = [("student", "q1"), ("tutor", "a1"), ("student", "q2"), ("assistant", "a2")]
    assert pairs_to_exchanges(transcript) == [
        {"student": "q1", "tutor": "a1"},
        {"student": "q2", "tutor": "a2"},
    ]


def test_pairs_to_exchanges_handles_trailing_student_and_leading_tutor():
    # trailing student with no reply, and a leading tutor greeting
    transcript = [("tutor", "hi!"), ("student", "q1")]
    assert pairs_to_exchanges(transcript) == [
        {"student": "", "tutor": "hi!"},
        {"student": "q1", "tutor": ""},
    ]


def test_grade_to_verdict_pass_threshold():
    v = grade_to_verdict(_grade(SCORE_THRESHOLD), topics=["EOQ"])
    assert v.worked_well is True                     # 32 >= 32
    assert v.one_line == "Solid Socratic guidance."
    assert v.topics == ["EOQ"]
    assert v.grade["total_score"] == SCORE_THRESHOLD  # full grade retained


def test_grade_to_verdict_below_threshold_is_bad():
    v = grade_to_verdict(_grade(SCORE_THRESHOLD - 1))
    assert v.worked_well is False


def test_grade_to_verdict_maps_deductions_to_issues_with_severity():
    deductions = [
        {"sub_criterion_id": "1.1.A.a", "reason": "gave the final answer", "points": 12},
        {"sub_criterion_id": "1.1.B.c", "reason": "minor phrasing", "points": 3},
        {"sub_criterion_id": "1.1.C.d", "reason": "tiny nit", "points": 1},
    ]
    v = grade_to_verdict(_grade(20, deductions))
    # sorted by points desc; severity high>=5, medium>=2, low otherwise
    assert [i["severity"] for i in v.issues] == ["high", "medium", "low"]
    assert v.issues[0]["type"] == "1.1.A.a"
    assert v.issues[0]["quote"] == "gave the final answer"
    assert v.issues[0]["points"] == 12


def test_rubric_judge_composes_payload_grade_and_topics():
    captured = {}

    def fake_grade_fn(payload, model):
        captured["payload"] = payload
        captured["model"] = model
        return _grade(33)

    def fake_topics_fn(course, transcript, model):
        captured["topics_course"] = course
        return ["reorder point"]

    j = RubricJudge(grade_fn=fake_grade_fn, topics_fn=fake_topics_fn)
    v = j.judge("Operations Mgmt", [("student", "q"), ("tutor", "a")], exercise="EOQ problem")

    assert v.worked_well is True
    assert v.grade == _grade(33)
    assert v.topics == ["reorder point"]
    assert captured["model"] == DEFAULT_JUDGE_MODEL
    assert captured["payload"]["course"] == ""                 # figure discovery disabled
    assert captured["payload"]["context"] == "Operations Mgmt"  # display name -> context
    assert captured["payload"]["exercise"] == "EOQ problem"
    assert captured["payload"]["exchanges"] == [{"student": "q", "tutor": "a"}]
    assert captured["topics_course"] == "Operations Mgmt"
