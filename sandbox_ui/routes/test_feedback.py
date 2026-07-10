"""Route tests for POST /api/feedback (validation + ownership).

The happy path (200 + row) needs a session-owned conversation, which requires a
real chat turn; that is covered by manual/live verification. These tests lock in
the rejection paths, which need no seeded conversation.
"""

import uuid


def test_bad_rating_rejected(client):
    resp = client.post("/api/feedback", json={"conversation_id": str(uuid.uuid4()), "rating": 9})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "bad_rating"


def test_non_integer_rating_rejected(client):
    resp = client.post("/api/feedback", json={"conversation_id": str(uuid.uuid4()), "rating": "great"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "bad_rating"


def test_missing_conversation_rejected(client):
    resp = client.post("/api/feedback", json={"rating": 4})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "missing_conversation"


def test_unowned_conversation_rejected(client):
    # A well-formed but non-existent conversation is not owned by this session.
    resp = client.post("/api/feedback", json={"conversation_id": str(uuid.uuid4()), "rating": 4})
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "wrong_session"
