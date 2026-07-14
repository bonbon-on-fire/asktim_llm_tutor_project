from tutor.cached_history import tutor_output_json, build_message_plan
from tutor.run_tutor import build_anthropic_request, _MAX_MSG_BREAKPOINTS


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


def test_build_anthropic_request_shapes_roles_and_caches_static():
    plan = [
        ("system_static", "SYS"),
        ("student", "s1"), ("rag", "r1"), ("tutor", "t1"),
        ("student", "s2"), ("rag", "r2"),
    ]
    system_blocks, messages = build_anthropic_request(plan)
    # static system is one cache-marked block
    assert system_blocks == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    # roles map: student->user, tutor->assistant, rag->system
    assert [m["role"] for m in messages] == ["user", "system", "assistant", "user", "system"]
    assert messages[0]["content"] == "s1" and messages[1]["content"] == "r1"
    # last message carries a cache breakpoint (as a content block)
    last = messages[-1]
    assert isinstance(last["content"], list) and last["content"][-1]["cache_control"] == {"type": "ephemeral"}


def test_build_anthropic_request_caps_breakpoints_on_long_conversations():
    # ~20 prior turns, each yielding 3 message blocks (student, rag, tutor),
    # plus a current student + current rag block -> well past the old scheme's
    # unbounded 15/30/45/... breakpoint accumulation.
    prior_turns = [
        {"student_content": f"s{i}", "rag_text": f"r{i}", "tutor_json": f"t{i}"}
        for i in range(20)
    ]
    plan = build_message_plan(
        static_system="SYS",
        prior_turns=prior_turns,
        current_student="s_current",
        current_rag="r_current",
    )
    system_blocks, messages = build_anthropic_request(plan)

    def has_cache_control(msg):
        content = msg["content"]
        return isinstance(content, list) and any("cache_control" in block for block in content)

    marked_count = sum(1 for m in messages if has_cache_control(m))
    assert marked_count <= _MAX_MSG_BREAKPOINTS
    assert marked_count <= 3
    total_breakpoints = len(system_blocks) + marked_count
    assert total_breakpoints <= 4

    # rolling write breakpoint: the last message is still marked
    assert has_cache_control(messages[-1])
