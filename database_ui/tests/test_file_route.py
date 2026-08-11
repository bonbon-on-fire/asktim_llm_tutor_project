# database_ui/tests/test_file_route.py
"""Route test for the /api/file/<id> download endpoint (unscoped review tool)."""

from __future__ import annotations

import pytest

from database_ui.conftest import seed
from database_ui.db.session import SessionLocal
from database_ui.run_app import create_app


@pytest.fixture()
def client():
    app = create_app()
    # Disable the auth gate so tests hit the API directly.
    app.config["DATABASE_UI_PASSWORD"] = None
    return app.test_client()


@pytest.fixture()
def seeded():
    from database_ui.db.models import (
        Conversation,
        Message,
        UploadedFile,
        UploadedImage,
    )
    session = SessionLocal()
    session.query(UploadedImage).delete()
    session.query(UploadedFile).delete()
    session.query(Message).delete()
    session.query(Conversation).delete()
    session.commit()
    ids = seed(session)
    # The seeded student turn carries exactly one UploadedFile ("data.csv").
    file_row = (
        session.query(UploadedFile)
        .filter(UploadedFile.message_id == ids["m_student_id"])
        .one()
    )
    ids["file_id"] = file_row.id
    session.close()
    return ids


def test_file_download_serves_bytes_as_attachment(client, seeded):
    resp = client.get(f"/api/file/{seeded['file_id']}")
    assert resp.status_code == 200
    assert resp.get_data() == b"col1,col2\n1,2"
    disposition = resp.headers["Content-Disposition"]
    assert disposition.startswith("attachment;")
    assert 'filename="data.csv"' in disposition
    # Served as an opaque download, not sniffed as text.
    assert resp.headers["Content-Type"].startswith("application/octet-stream")


def test_file_download_unknown_id_is_404(client, seeded):
    resp = client.get("/api/file/999999")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "not_found"
