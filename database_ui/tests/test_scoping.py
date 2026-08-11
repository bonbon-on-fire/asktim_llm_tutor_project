"""End-to-end scope enforcement across login and every read path."""

from __future__ import annotations

import pytest

from database_ui.conftest import seed
from database_ui.db.models import UploadedFile, UploadedImage
from database_ui.db.session import SessionLocal
from database_ui.run_app import create_app

MASTER = "master-secret"
SC_PW = "supply-secret"      # scoped to supply_chain_design
MOL_PW = "meaning-secret"    # scoped to meaning_of_life


def _app():
    app = create_app()
    app.config["DATABASE_UI_PASSWORD"] = MASTER
    app.config["DATABASE_UI_COURSE_PASSWORDS"] = {
        SC_PW: ("supply_chain_design",),
        MOL_PW: ("meaning_of_life",),
    }
    return app


def _login(app, password):
    client = app.test_client()
    client.post("/login", data={"password": password})
    return client


@pytest.fixture()
def seeded():
    from database_ui.db.models import Conversation, Message
    session = SessionLocal()
    session.query(UploadedImage).delete()
    session.query(UploadedFile).delete()
    session.query(Message).delete()
    session.query(Conversation).delete()
    session.commit()
    ids = seed(session)
    # seed() attaches one image and one file to the supply_chain student message.
    ids["image_id"] = session.query(UploadedImage.id).scalar()
    ids["file_id"] = session.query(UploadedFile.id).scalar()
    session.close()
    return ids


def test_scoped_password_logs_in():
    resp = _app().test_client().post("/login", data={"password": SC_PW})
    assert resp.status_code == 302


def test_unknown_password_is_rejected():
    resp = _app().test_client().post("/login", data={"password": "nope"})
    assert resp.status_code == 401


@pytest.mark.parametrize("password", [MASTER, SC_PW, MOL_PW])
def test_index_scope_marker_is_hidden_styling(password):
    # The scope marker lives in the banner but is rendered as background-colored
    # (hidden) text -- a scoped reviewer shouldn't be able to tell the view is
    # filtered without deliberately selecting the header text.
    body = _login(_app(), password).get("/").get_data(as_text=True)
    assert "scope-hidden" in body


def test_index_master_marker_reads_master():
    body = _login(_app(), MASTER).get("/").get_data(as_text=True)
    assert "Master" in body


def test_index_scoped_marker_reads_course_name():
    # supply_chain_design -> its display name, present (but hidden) in the banner.
    body = _login(_app(), SC_PW).get("/").get_data(as_text=True)
    assert "MIT CTL.SC2x Supply Chain Design" in body


def test_scoped_list_shows_only_own_course(seeded):
    client = _login(_app(), SC_PW)
    data = client.get("/api/conversations").get_json()
    courses = {c["course"] for c in data["conversations"]}
    assert courses == {"supply_chain_design"}


def test_master_list_shows_all_courses(seeded):
    client = _login(_app(), MASTER)
    data = client.get("/api/conversations").get_json()
    courses = {c["course"] for c in data["conversations"]}
    assert courses == {"supply_chain_design", "meaning_of_life"}


def test_scoped_view_blocks_other_course_conversation(seeded):
    client = _login(_app(), SC_PW)
    assert client.get(f"/api/conversation/{seeded['mol_id']}").status_code == 404
    assert client.get(f"/api/conversation/{seeded['sc_id']}").status_code == 200


def test_scoped_export_filters_show_only_own_course(seeded):
    client = _login(_app(), MOL_PW)
    data = client.get("/api/export/filters").get_json()
    assert [c["course"] for c in data["courses"]] == ["meaning_of_life"]


def test_scoped_export_rows_cannot_pull_other_course(seeded):
    # Scoped to meaning_of_life, request supply_chain_design's rows (which DO
    # exist) -> the scope filter drops them, leaving a header-only CSV.
    client = _login(_app(), MOL_PW)
    resp = client.get("/api/export.csv?assignment=supply_chain_design::1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True).lstrip("﻿")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) == 1  # header only, no supply_chain rows


def test_master_export_rows_include_supply_chain(seeded):
    client = _login(_app(), MASTER)
    resp = client.get("/api/export.csv?assignment=supply_chain_design::1")
    body = resp.get_data(as_text=True).lstrip("﻿")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) >= 3  # header + 2 message rows


def test_scoped_user_cannot_fetch_other_course_image(seeded):
    # image belongs to supply_chain_design; a meaning_of_life user must get 404.
    client = _login(_app(), MOL_PW)
    assert client.get(f"/api/image/{seeded['image_id']}").status_code == 404


def test_scoped_user_can_fetch_own_course_image(seeded):
    client = _login(_app(), SC_PW)
    assert client.get(f"/api/image/{seeded['image_id']}").status_code == 200


def test_scoped_user_cannot_fetch_other_course_file(seeded):
    client = _login(_app(), MOL_PW)
    assert client.get(f"/api/file/{seeded['file_id']}").status_code == 404


def test_master_can_fetch_image_and_file(seeded):
    client = _login(_app(), MASTER)
    assert client.get(f"/api/image/{seeded['image_id']}").status_code == 200
    assert client.get(f"/api/file/{seeded['file_id']}").status_code == 200
