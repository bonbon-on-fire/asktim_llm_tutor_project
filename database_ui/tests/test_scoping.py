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


def test_index_shows_scope_label():
    body = _login(_app(), SC_PW).get("/").get_data(as_text=True)
    assert "MIT CTL.SC2x Supply Chain Design" in body
