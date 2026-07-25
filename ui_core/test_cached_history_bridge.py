"""Tests for the cached-history dispatch branch in ui_core.tutor_bridge.

Covers the module-level env gate (`cached_history_enabled`) and the GPT
cached-mode branch of `TutorBridge.stream_tutor_reply`, which builds an
interleaved (system, human, system, ai, human, system) message plan via
`tutor.cached_history.build_message_plan` and streams it through the
already-cached langchain model (rather than the legacy flattened-history
path used when `history_mode == "legacy"`).
"""

from __future__ import annotations

from unittest.mock import patch

from ui_core.tutor_bridge import TutorBridge, cached_history_enabled


def test_cached_history_enabled_defaults_on(monkeypatch):
    # Cached interleaved history is now the DEFAULT path.
    monkeypatch.delenv("TUTOR_CACHED_HISTORY", raising=False)
    assert cached_history_enabled() is True
    # Explicit falsey values force the legacy fallback.
    monkeypatch.setenv("TUTOR_CACHED_HISTORY", "off")
    assert cached_history_enabled() is False
    monkeypatch.setenv("TUTOR_CACHED_HISTORY", "0")
    assert cached_history_enabled() is False
    # Any other value keeps cached.
    monkeypatch.setenv("TUTOR_CACHED_HISTORY", "1")
    assert cached_history_enabled() is True


def test_cached_gpt_builds_interleaved_messages():
    bridge = TutorBridge()
    captured = {}

    class FakeChunk:  # mimics langchain AIMessageChunk
        content = '{"pedagogical-reasoning":"r","Student-facing-answer":"hi"}'

    class FakeModel:
        def stream(self, messages, **kw):
            captured["messages"] = messages
            return iter([FakeChunk()])

    with patch.object(
        bridge, "_get_or_build_stream_context", return_value=(FakeModel(), "SYS")
    ), patch.object(
        bridge,
        "retrieved_context",
        return_value=type(
            "RC",
            (),
            {"text": "RAGNOW", "records": [{"source": "x", "text": "t"}], "embedding_tokens": 0},
        )(),
    ), patch.object(bridge, "_enforce_rag_available"):
        list(
            bridge.stream_tutor_reply(
                course="c",
                exercise="1",
                tutor="tutor_07",
                history=[],
                new_student_message="hello",
                provider="gpt",
                history_mode="cached",
                cached_history=[
                    {"student_content": "s1", "rag_text": "R1", "tutor_json": "T1"}
                ],
            )
        )
    roles = [type(m).__name__ for m in captured["messages"]]
    # SystemMessage(static), Human(s1), System(R1), AI(T1), Human(hello), System(RAGNOW)
    assert roles == [
        "SystemMessage",
        "HumanMessage",
        "SystemMessage",
        "AIMessage",
        "HumanMessage",
        "SystemMessage",
    ]


def test_cached_gpt_attaches_current_turn_images():
    # A pasted table (image upload) must ride on the CURRENT student turn in
    # cached mode, not be dropped — the GPT/langchain path.
    bridge = TutorBridge()
    captured = {}

    class FakeChunk:
        content = '{"pedagogical-reasoning":"r","Student-facing-answer":"hi"}'

    class FakeModel:
        def stream(self, messages, **kw):
            captured["messages"] = messages
            return iter([FakeChunk()])

    with patch.object(
        bridge, "_get_or_build_stream_context", return_value=(FakeModel(), "SYS")
    ), patch.object(
        bridge,
        "retrieved_context",
        return_value=type(
            "RC", (), {"text": "", "records": [], "embedding_tokens": 0}
        )(),
    ), patch.object(bridge, "_enforce_rag_available"):
        list(
            bridge.stream_tutor_reply(
                course="c",
                exercise="1",
                tutor="tutor_07",
                history=[],
                new_student_message="read this table",
                images=[(b"\x89PNGDATA", "image/png")],
                provider="gpt",
                history_mode="cached",
                cached_history=[],
            )
        )
    # Messages: SystemMessage(static), HumanMessage(current student with image)
    human = captured["messages"][-1]
    assert type(human).__name__ == "HumanMessage"
    assert isinstance(human.content, list), human.content
    assert any(b.get("type") == "text" and b["text"] == "read this table" for b in human.content)
    image_blocks = [b for b in human.content if b.get("type") == "image_url"]
    assert len(image_blocks) == 1
    assert image_blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_cached_gpt_replays_prior_turn_images():
    # An image uploaded on an EARLIER turn must still ride on that prior student
    # turn when the conversation is replayed (not just the current turn) — the
    # GPT/langchain cached path.
    bridge = TutorBridge()
    captured = {}

    class FakeChunk:
        content = '{"pedagogical-reasoning":"r","Student-facing-answer":"hi"}'

    class FakeModel:
        def stream(self, messages, **kw):
            captured["messages"] = messages
            return iter([FakeChunk()])

    with patch.object(
        bridge, "_get_or_build_stream_context", return_value=(FakeModel(), "SYS")
    ), patch.object(
        bridge,
        "retrieved_context",
        return_value=type(
            "RC", (), {"text": "", "records": [], "embedding_tokens": 0}
        )(),
    ), patch.object(bridge, "_enforce_rag_available"):
        list(
            bridge.stream_tutor_reply(
                course="c",
                exercise="1",
                tutor="tutor_07",
                history=[],
                new_student_message="follow-up, no new image",
                provider="gpt",
                history_mode="cached",
                cached_history=[
                    {
                        "student_content": "look at my screenshot",
                        "rag_text": "",
                        "tutor_json": "T1",
                        "images": [(b"\x89PNGDATA", "image/png")],
                    }
                ],
            )
        )
    # Messages: SystemMessage(static), HumanMessage(prior student w/ image),
    # AIMessage(T1), HumanMessage(current student, no image).
    prior_student = captured["messages"][1]
    assert type(prior_student).__name__ == "HumanMessage"
    assert isinstance(prior_student.content, list), prior_student.content
    assert any(
        b.get("type") == "text" and b["text"] == "look at my screenshot"
        for b in prior_student.content
    )
    prior_imgs = [b for b in prior_student.content if b.get("type") == "image_url"]
    assert len(prior_imgs) == 1
    # The current student turn (last) had no new image -> stays plain text.
    current_student = captured["messages"][-1]
    assert isinstance(current_student.content, str)


def test_cached_claude_threads_images_by_student_to_raw_sender():
    # Default (claude) path: the bridge must hand the raw Anthropic sender a
    # per-student-turn image list — [prior turn images..., current turn images] —
    # so prior screenshots are replayed and the current upload still rides.
    bridge = TutorBridge()
    captured = {}

    def fake_raw(plan, *, model_name, api_key, images=None, images_by_student=None):
        captured["images_by_student"] = images_by_student
        captured["images"] = images
        yield ("__done__", '{"pedagogical-reasoning":"r","Student-facing-answer":"hi"}', None)

    with patch.object(
        bridge, "_get_or_build_stream_context", return_value=(object(), "SYS")
    ), patch.object(
        bridge,
        "retrieved_context",
        return_value=type("RC", (), {"text": "", "records": [], "embedding_tokens": 0})(),
    ), patch.object(bridge, "_enforce_rag_available"), patch(
        "ui_core.tutor_bridge.stream_tutor_reply_anthropic_raw", fake_raw
    ), patch(
        "ui_core.tutor_bridge._require_anthropic_api_key", return_value="k"
    ):
        list(
            bridge.stream_tutor_reply(
                course="c",
                exercise="1",
                tutor="tutor_07",
                history=[],
                new_student_message="current",
                images=[(b"CURRENT", "image/png")],
                history_mode="cached",
                cached_history=[
                    {
                        "student_content": "s1",
                        "rag_text": "",
                        "tutor_json": "T1",
                        "images": [(b"PRIOR", "image/jpeg")],
                    },
                    {"student_content": "s2", "rag_text": "", "tutor_json": "T2"},
                ],
            )
        )
    # Aligned to student steps: prior turn 1 (image), prior turn 2 (none), current.
    assert captured["images_by_student"] == [
        [(b"PRIOR", "image/jpeg")],
        [],
        [(b"CURRENT", "image/png")],
    ]
