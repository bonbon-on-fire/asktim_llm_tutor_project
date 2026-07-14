from tutor.cached_history import tutor_output_json, build_message_plan


def test_tutor_output_json_is_canonical_and_stable():
    a = tutor_output_json("reasoned", "answer")
    b = tutor_output_json("reasoned", "answer")
    assert a == b  # byte-stable
    assert a == '{"pedagogical-reasoning": "reasoned", "Student-facing-answer": "answer"}'
    # None coerces to empty string, never null
    assert tutor_output_json(None, "x") == '{"pedagogical-reasoning": "", "Student-facing-answer": "x"}'


def test_build_message_plan_interleaves_rag_after_student():
    plan = build_message_plan(
        static_system="SYS",
        prior_turns=[
            {"student_content": "s1", "rag_text": "r1", "tutor_json": "t1"},
            {"student_content": "s2", "rag_text": "r2", "tutor_json": "t2"},
        ],
        current_student="s3",
        current_rag="r3",
    )
    assert plan == [
        ("system_static", "SYS"),
        ("student", "s1"), ("rag", "r1"), ("tutor", "t1"),
        ("student", "s2"), ("rag", "r2"), ("tutor", "t2"),
        ("student", "s3"), ("rag", "r3"),
    ]


def test_build_message_plan_omits_empty_current_rag():
    plan = build_message_plan(static_system="SYS", prior_turns=[], current_student="s1", current_rag="")
    assert plan == [("system_static", "SYS"), ("student", "s1")]


def test_build_message_plan_omits_empty_prior_rag():
    plan = build_message_plan(
        static_system="SYS",
        prior_turns=[{"student_content": "s1", "rag_text": "", "tutor_json": "t1"}],
        current_student="s2",
        current_rag="r2",
    )
    assert plan == [("system_static", "SYS"), ("student", "s1"), ("tutor", "t1"), ("student", "s2"), ("rag", "r2")]
