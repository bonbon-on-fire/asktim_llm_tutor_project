"""Route test: a /api/chat turn's custom_* fields are ignored (feature removed).

The conversation is created against the built-in course/exercise, and no custom
text reaches the tutor bridge. The tutor stream is stubbed so no live LLM call runs.
"""

from __future__ import annotations

import sandbox_ui.services.tutor_bridge as tutor_bridge


def _fake_stream(**kwargs):
    """Capture kwargs, yield one delta + done. Records into _CAPTURED."""
    _CAPTURED.clear()
    _CAPTURED.update(kwargs)
    yield {"type": "delta", "text": "hi"}
    yield {"type": "done", "reply": "hi", "reasoning": None, "retrieved": None}


_CAPTURED: dict = {}


def test_custom_fields_are_ignored(client, monkeypatch):
    """A course_custom in the request does not change the stored course or reach the bridge."""
    monkeypatch.setattr(tutor_bridge, "stream_tutor_reply", _fake_stream)
    resp = client.post(
        "/api/chat",
        json={
            "text": "hello",
            "course": "cities_and_climate_change",
            "exercise": "4",
            "course_custom": "MALICIOUS OVERRIDE TEXT",
            "exercise_custom": "X",
            "tutor_custom": "Y",
        },
    )
    assert resp.status_code == 200
    # The bridge must have been called for the built-in course, with no custom kwargs.
    assert _CAPTURED.get("course") == "cities_and_climate_change"
    assert "course_text" not in _CAPTURED
    assert "exercise_text" not in _CAPTURED
    assert "custom_tutor_prompt" not in _CAPTURED
    assert "MALICIOUS OVERRIDE TEXT" not in str(_CAPTURED)
