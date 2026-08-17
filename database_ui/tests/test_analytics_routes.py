# database_ui/tests/test_analytics_routes.py
import json

import pytest

from database_ui.conftest import seed
from database_ui.db.session import SessionLocal
from database_ui.run_app import create_app
from database_ui.analytics import cache as cache_mod

MASTER = "master-secret"
SC_PW = "supply-secret"


@pytest.fixture()
def seeded():
    s = SessionLocal()
    seed(s)
    s.close()


def _app():
    app = create_app()
    app.config["DATABASE_UI_PASSWORD"] = MASTER
    app.config["DATABASE_UI_COURSE_PASSWORDS"] = {SC_PW: ("supply_chain_design",)}
    return app


def _login(app, pw):
    c = app.test_client()
    c.post("/login", data={"password": pw})
    return c


def test_analytics_page_requires_auth():
    app = _app()
    resp = app.test_client().get("/analytics")
    assert resp.status_code in (301, 302)          # redirected to login


def test_api_analytics_returns_live_and_pending_cached(seeded):
    c = _login(_app(), MASTER)
    resp = c.get("/api/analytics?week=2026-05-01")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "live" in body and "week" in body
    assert body["cached"] is None                  # no cache committed for that week


def test_api_analytics_scoped(seeded):
    c = _login(_app(), SC_PW)
    body = c.get("/api/analytics?week=2026-05-01").get_json()
    assert set(body["live"]["per_course"]) <= {"supply_chain_design"}


def test_api_weeks_lists_options(seeded):
    c = _login(_app(), MASTER)
    body = c.get("/api/analytics/weeks").get_json()
    assert "weeks" in body and isinstance(body["weeks"], list)
    # The calendar picker's bounds: earliest data week <= latest complete week.
    rng = body["range"]
    assert rng["min"] <= rng["max"]
    assert rng["min"] == "2026-04-26"          # week containing the May 1 seed rows


def test_api_analytics_passes_grade_through(seeded, tmp_path, monkeypatch):
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    grade = {"total_score": 20, "max_score": 40, "overview": "gave away the answer"}
    blob = {
        "conversations": {
            "conv-1": {
                "course": "supply_chain_design",
                "worked_well": False,
                "issues": [],
                "topics": [],
                "one_line": "handed it over",
                "grade": grade,
            }
        },
        "examples": {"exemplary": [], "high_engagement": [], "sample": {}},
        "topics_by_course": {},
    }
    (tmp_path / "2026-04-26.json").write_text(json.dumps(blob), encoding="utf-8")

    c = _login(_app(), MASTER)
    body = c.get("/api/analytics?week=2026-05-01").get_json()
    conv = body["cached"]["conversations"]["conv-1"]
    assert conv["grade"] == grade
    assert conv["worked_well"] is False
