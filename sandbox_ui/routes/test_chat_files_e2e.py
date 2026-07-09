"""End-to-end test: a file attached on turn 1 is still visible to the tutor
in the history built for a later turn.

Drives the real ``/api/chat`` route (multipart upload -> validate -> persist ->
stream -> commit) through the Flask test client, so it exercises the whole
persist-across-turns path — not just the ``get_history_for_tutor`` helper unit
already covered by ``ui_core/services/test_conversation.py``.

The tutor stream (``sandbox_ui.services.tutor_bridge.stream_tutor_reply``) is
monkeypatched to a canned generator so the test never makes a live LLM/network
call: the real function is swapped out entirely for the duration of the test,
so its body (which would reach out to a model provider) never runs.

Run with:
    python -m pytest sandbox_ui/routes/test_chat_files_e2e.py -q
"""

from __future__ import annotations

import io
import json
import re
import uuid

from sandbox_ui.db.models import Conversation
from sandbox_ui.services import tutor_bridge
from sandbox_ui.services.conversation import get_history_for_tutor


def _fake_stream_tutor_reply(**_kwargs):
    """Canned tutor reply: one delta chunk, then the terminal done event.

    Shape matches what ``sandbox_ui.routes.chat.event_stream`` expects from
    the real bridge (see chat.py's consumption of "delta"/"done" event dicts).
    No network or LLM call happens here — this fully replaces the real
    generator for the duration of the test.
    """
    yield {"type": "delta", "text": "Got it."}
    yield {"type": "done", "reply": "Got it.", "reasoning": None, "retrieved": None}


_DONE_RE = re.compile(r"event: done\ndata: (\{.*\})\n\n")


def _parse_done_event(sse_text: str) -> dict:
    """Extract and parse the JSON payload of the SSE 'done' event."""
    match = _DONE_RE.search(sse_text)
    assert match, f"no 'done' SSE event found in response: {sse_text!r}"
    return json.loads(match.group(1))


def test_file_persists_into_history_on_later_turn(client, db_session, monkeypatch):
    """Attach a CSV on turn 1; two more text-only turns follow; the tutor
    history built for the conversation still carries the attachment text.
    """
    monkeypatch.setattr(tutor_bridge, "stream_tutor_reply", _fake_stream_tutor_reply)

    # Turn 1: text + a CSV attachment, starting a brand new conversation.
    resp1 = client.post(
        "/api/chat",
        data={
            "text": "here is my data",
            "course": "supply_chain_design",
            "exercise": "1",
            "files": [(io.BytesIO(b"region,cost\nA,10\n"), "d.csv")],
        },
        content_type="multipart/form-data",
    )
    assert resp1.status_code == 200
    done1 = _parse_done_event(resp1.get_data(as_text=True))
    conversation_id = done1["conversation_id"]

    # Turn 2 and 3: text-only continuations of the same conversation.
    for turn_text in ("what should I do next?", "can you clarify that?"):
        resp = client.post(
            "/api/chat",
            json={
                "text": turn_text,
                "course": "supply_chain_design",
                "exercise": "1",
                "conversation_id": conversation_id,
            },
        )
        assert resp.status_code == 200
        _parse_done_event(resp.get_data(as_text=True))

    # Build the history the tutor would see for a hypothetical next turn, and
    # confirm the turn-1 attachment is still injected into the student content.
    convo = db_session.get(Conversation, uuid.UUID(conversation_id))
    assert convo is not None
    history = get_history_for_tutor(db_session, convo)

    student_turns = [h for h in history if h["role"] == "student"]
    assert len(student_turns) == 3
    assert any(
        "[Attachment: d.csv]" in h["content"] and "region" in h["content"]
        for h in student_turns
    )
    # The later, file-less turns must not themselves carry an attachment block.
    assert "[Attachment:" not in student_turns[1]["content"]
    assert "[Attachment:" not in student_turns[2]["content"]


def test_text_only_conversation_has_no_attachment_leak(client, db_session, monkeypatch):
    """Guard: a conversation that never had a file attached shows no
    attachment block anywhere in its tutor-facing history (no cross-turn or
    cross-conversation leakage of attachment text).
    """
    monkeypatch.setattr(tutor_bridge, "stream_tutor_reply", _fake_stream_tutor_reply)

    resp1 = client.post(
        "/api/chat",
        json={
            "text": "just a question, no files",
            "course": "supply_chain_design",
            "exercise": "1",
        },
    )
    assert resp1.status_code == 200
    done1 = _parse_done_event(resp1.get_data(as_text=True))
    conversation_id = done1["conversation_id"]

    resp2 = client.post(
        "/api/chat",
        json={
            "text": "a follow-up",
            "course": "supply_chain_design",
            "exercise": "1",
            "conversation_id": conversation_id,
        },
    )
    assert resp2.status_code == 200
    _parse_done_event(resp2.get_data(as_text=True))

    convo = db_session.get(Conversation, uuid.UUID(conversation_id))
    assert convo is not None
    history = get_history_for_tutor(db_session, convo)

    assert history, "expected some history to have been recorded"
    assert all("[Attachment:" not in h["content"] for h in history)
