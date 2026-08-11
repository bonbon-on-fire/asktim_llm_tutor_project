"""Route test: the /api/file/<id> download endpoint enforces owner-only access.

Attaches a CSV on a real /api/chat turn (multipart upload -> validate ->
persist), then drives the new download endpoint:

- the SAME client (carrying the session cookie that started the conversation)
  downloads the bytes, served as an attachment under the original filename;
- a FRESH client (no session cookie, no username) gets 404 — not 403 — so file
  ids can't be probed.

The tutor stream is monkeypatched to a canned generator so no LLM/network call
happens.

Run with:
    python -m pytest sandbox_ui/routes/test_file_download.py -q
"""

from __future__ import annotations

import io
import json
import re
import uuid

from sandbox_ui.db.models import Conversation, Message, UploadedFile
from sandbox_ui.services import tutor_bridge


def _fake_stream_tutor_reply(**_kwargs):
    """Canned tutor reply (one delta + terminal done); no network/LLM call."""
    yield {"type": "delta", "text": "Got it."}
    yield {"type": "done", "reply": "Got it.", "reasoning": None, "retrieved": None}


_DONE_RE = re.compile(r"event: done\ndata: (\{.*\})\n\n")


def _conversation_id(sse_text: str) -> str:
    """Pull the conversation_id out of the SSE 'done' event."""
    match = _DONE_RE.search(sse_text)
    assert match, f"no 'done' SSE event found: {sse_text!r}"
    return json.loads(match.group(1))["conversation_id"]


def _uploaded_file_id(db_session, conversation_id: str) -> int:
    """Return the id of the single UploadedFile on *conversation_id*'s messages."""
    convo_uuid = uuid.UUID(conversation_id)
    message_ids = [
        m.id
        for m in db_session.query(Message).filter(
            Message.conversation_id == convo_uuid
        )
    ]
    rows = (
        db_session.query(UploadedFile)
        .filter(UploadedFile.message_id.in_(message_ids))
        .all()
    )
    assert len(rows) == 1, f"expected exactly one uploaded file, got {len(rows)}"
    return rows[0].id


def test_owner_downloads_file_stranger_gets_404(client, db_session, monkeypatch):
    """The uploading session downloads the bytes; a fresh session is 404'd."""
    monkeypatch.setattr(tutor_bridge, "stream_tutor_reply", _fake_stream_tutor_reply)

    resp = client.post(
        "/api/chat",
        data={
            "text": "here is my data",
            "course": "supply_chain_design",
            "exercise": "1",
            "files": [(io.BytesIO(b"region,cost\nA,10\n"), "d.csv")],
        },
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    conversation_id = _conversation_id(resp.get_data(as_text=True))
    file_id = _uploaded_file_id(db_session, conversation_id)

    # The same client still carries the session cookie -> it owns the file.
    owned = client.get(f"/api/file/{file_id}")
    assert owned.status_code == 200
    assert owned.get_data() == b"region,cost\nA,10\n"
    disposition = owned.headers["Content-Disposition"]
    assert disposition.startswith("attachment;")
    assert 'filename="d.csv"' in disposition

    # A fresh client (no session cookie, no username) must not reach the bytes,
    # and gets 404 (never 403) so ids can't be probed.
    from sandbox_ui.run_app import app as _app

    with _app.test_client() as stranger:
        denied = stranger.get(f"/api/file/{file_id}")
    assert denied.status_code == 404

    # An unknown id is likewise 404.
    assert client.get("/api/file/999999").status_code == 404
