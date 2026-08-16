from database_ui.analytics.judge import FakeJudge, Verdict, transcript_hash, ISSUE_TYPES


def test_transcript_hash_is_stable_and_content_sensitive():
    a = [("student", "hi"), ("tutor", "hello")]
    b = [("student", "hi"), ("tutor", "different")]
    assert transcript_hash(a) == transcript_hash(a)
    assert transcript_hash(a) != transcript_hash(b)


def test_fake_judge_returns_canned_then_default():
    v = Verdict(worked_well=False,
                issues=[{"type": "gave_away_answer", "severity": "high", "quote": "..."}],
                topics=["EOQ"], one_line="gave answer")
    d = Verdict(worked_well=True, issues=[], topics=[], one_line="ok")
    j = FakeJudge(canned={"u1": v}, default=d)
    # FakeJudge keys on the LAST student line of the transcript.
    assert j.judge("c1", [("student", "u1")]) == v          # canned match wins
    assert j.judge("c1", [("student", "other")]) == d       # otherwise the default


def test_issue_types_are_the_four_agreed():
    assert ISSUE_TYPES == ("gave_away_answer", "factual_error", "unhelpful_dead_end", "rag_grounding")
