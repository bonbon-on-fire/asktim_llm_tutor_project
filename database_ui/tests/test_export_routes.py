# database_ui/tests/test_export_routes.py
"""Route tests for the CSV export endpoints."""

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
    session.close()
    return ids


def test_filters_endpoint_returns_courses(client, seeded):
    resp = client.get("/api/export/filters")
    assert resp.status_code == 200
    data = resp.get_json()
    keys = [c["course"] for c in data["courses"]]
    assert keys == ["meaning_of_life", "supply_chain_design"]


def test_export_csv_headers_and_bom(client, seeded):
    resp = client.get("/api/export.csv?assignment=supply_chain_design::1")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/csv")
    assert "attachment" in resp.headers["Content-Disposition"]
    body = resp.get_data(as_text=True)
    assert body.startswith("﻿")  # UTF-8 BOM
    # Header row present with the first and last declared columns.
    header_line = body.lstrip("﻿").splitlines()[0]
    assert header_line.startswith("conversation_id,")
    assert header_line.endswith(",created_at")
    # Two message rows for supply_chain_design exercise "1".
    assert body.count("\n") >= 2


def test_export_csv_filters_out_unselected(client, seeded):
    # Select only meaning_of_life "1" (no messages) -> header-only CSV.
    resp = client.get("/api/export.csv?assignment=meaning_of_life::1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True).lstrip("﻿")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) == 1  # header only


def test_export_csv_empty_selection_is_400(client, seeded):
    resp = client.get("/api/export.csv")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "bad_selection"


def test_export_csv_malformed_pair_is_400(client, seeded):
    # No "::" separator -> not a valid pair -> empty selection -> 400.
    resp = client.get("/api/export.csv?assignment=supply_chain_design")
    assert resp.status_code == 400
