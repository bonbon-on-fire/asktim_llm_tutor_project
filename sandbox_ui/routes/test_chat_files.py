"""Route-level tests for the non-image file-attachment wiring in /api/chat.

Both cases fail validation before any DB write or tutor call, so no stubbing
of the tutor stream is needed.

Run with:
    python -m pytest sandbox_ui/routes/test_chat_files.py -q
"""

import io

from utils.uploads import MAX_ATTACHMENTS_PER_MESSAGE


def test_too_many_attachments_rejected(client):
    data = {"text": "hi", "course": "supply_chain_design", "exercise": "1"}
    data["files"] = [(io.BytesIO(b"a,b\n1,2\n"), f"f{i}.csv") for i in range(4)]
    resp = client.post("/api/chat", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert resp.get_json()["error"] in ("too_many_attachments", "bad_file")


def test_bad_file_type_rejected(client):
    data = {"text": "hi", "course": "supply_chain_design", "exercise": "1",
            "files": [(io.BytesIO(b"MZ\x00"), "x.exe")]}
    resp = client.post("/api/chat", data=data, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "bad_file"
