# database_ui/tests/test_transcript_service.py
"""Tests for the transcript payload (get_messages_for_conversation)."""

from __future__ import annotations

from database_ui.conftest import seed
from database_ui.services import conversations as svc


def test_transcript_carries_images_and_attachments(db_session):
    ids = seed(db_session)
    convo = svc.get_conversation(db_session, ids["sc_id"])
    messages = svc.get_messages_for_conversation(db_session, convo)

    # student turn first, tutor second (ordered by turn then id).
    student, tutor = messages
    assert student["role"] == "student"

    # The student turn carries one image (id + mime, no bytes) ...
    assert [img["mime_type"] for img in student["images"]] == ["image/png"]
    assert "data" not in student["images"][0]

    # ... and one non-image attachment (filename + kind, no bytes).
    assert student["attachments"] == [
        {"id": student["attachments"][0]["id"], "filename": "data.csv", "kind": "csv"}
    ]
    assert "data" not in student["attachments"][0]
    assert "extracted_text" not in student["attachments"][0]

    # The tutor turn has neither.
    assert tutor["images"] == []
    assert tutor["attachments"] == []
