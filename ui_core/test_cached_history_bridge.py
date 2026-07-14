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
