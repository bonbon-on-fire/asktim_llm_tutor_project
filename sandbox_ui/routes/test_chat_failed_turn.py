"""A failed tutor turn is surfaced as an SSE error frame and persists no tutor row.

Parity with ``main_ui/routes/test_chat_failed_turn.py``. When the tutor can't
produce a valid answer, the bridge's ``done`` event carries ``failed: True``
(empty reply or the canned parse-failure fallback). The chat route must then
emit ``event: error`` — so the client shows "Tap to retry" — instead of a
``done`` frame, and must NOT write a tutor Message row. A normal reply still
yields ``done`` and persists the tutor row.

The tutor stream (``sandbox_ui.services.tutor_bridge.stream_tutor_reply``) is
monkeypatched to a canned generator, so no live LLM/network call happens.

Run with:
    python -m pytest sandbox_ui/routes/test_chat_failed_turn.py -q
"""

from __future__ import annotations

from sandbox_ui.db.models import Message
from sandbox_ui.services import tutor_bridge
from tutor.run_tutor import INVALID_RESPONSE_ANSWER

COURSE = "supply_chain_design"
EXERCISE = "1"


def _failed_stream(**_kwargs):
    # Bridge signals a failed turn: the canned fallback answer plus failed=True.
    yield {"type": "done", "reply": INVALID_RESPONSE_ANSWER, "reasoning": None, "failed": True}


def _ok_stream(**_kwargs):
    yield {"type": "delta", "text": "Here"}
    yield {"type": "done", "reply": "Here is a hint.", "reasoning": "r", "failed": False}


def _tutor_row_count(db_session) -> int:
    db_session.expire_all()  # force a fresh read of rows the route just committed
    return db_session.query(Message).filter(Message.role == "tutor").count()


def test_failed_turn_emits_error_and_persists_no_tutor_row(client, db_session, monkeypatch):
    monkeypatch.setattr(tutor_bridge, "stream_tutor_reply", _failed_stream)
    before = _tutor_row_count(db_session)

    resp = client.post(
        "/api/chat", json={"text": "hi", "course": COURSE, "exercise": EXERCISE}
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "event: error" in body
    assert "event: done" not in body
    # The canned fallback text must not be streamed as a visible bubble.
    assert INVALID_RESPONSE_ANSWER not in body
    # No tutor row persisted (matches the empty-reply / exception paths).
    assert _tutor_row_count(db_session) == before


def test_success_turn_emits_done_and_persists_tutor_row(client, db_session, monkeypatch):
    monkeypatch.setattr(tutor_bridge, "stream_tutor_reply", _ok_stream)
    before = _tutor_row_count(db_session)

    resp = client.post(
        "/api/chat", json={"text": "hi again", "course": COURSE, "exercise": EXERCISE}
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    assert "event: done" in body
    assert _tutor_row_count(db_session) == before + 1
