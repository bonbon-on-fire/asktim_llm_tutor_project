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
    # The calendar picker's bounds: earliest data week <= current in-progress week.
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


def test_course_scope_multi():
    """The course dropdown sends one ``course=`` per selected course. Out-of-scope
    keys are dropped, blanks ignored, and an empty/all selection falls back to the
    login's full scope so no login can widen past ``allowed``."""
    from database_ui.routes.analytics import _course_scope

    allowed = ["a", "b", "c"]
    assert _course_scope(allowed, ["a", "b"]) == ["a", "b"]      # subset kept, in order
    assert _course_scope(allowed, ["b", "z"]) == ["b"]           # out-of-scope "z" dropped
    assert _course_scope(allowed, ["a", "a", " a "]) == ["a"]    # de-duped + stripped
    assert _course_scope(allowed, []) == allowed                 # nothing selected -> full scope
    assert _course_scope(allowed, ["z"]) == allowed              # all out of scope -> full scope
    # Master (allowed=None) can filter to any keys it names, and empty falls back to None.
    assert _course_scope(None, ["x", "y"]) == ["x", "y"]
    assert _course_scope(None, []) is None


def test_flagged_meta_is_live_and_flag_only(seeded, tmp_path, monkeypatch):
    """The payload carries live label data for the flagged conversations only.

    Real seeded conversation ids get {exercise_*, last_active_at, message_count};
    conversations that worked well contribute nothing, and a non-UUID cache key
    is skipped rather than crashing the request.
    """
    from database_ui.services import conversations as conv_mod

    convs = conv_mod.list_all_conversations(SessionLocal())
    assert convs, "seed provides at least one conversation"
    real_id = convs[0]["id"]

    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    blob = {
        "conversations": {
            real_id: {                       # flagged + a real id -> gets meta
                "course": "supply_chain_design", "worked_well": False,
                "issues": [], "topics": [], "one_line": "x",
                "grade": {"total_score": 20, "max_score": 40, "overview": "o"},
            },
            "not-a-uuid": {                  # flagged but unresolvable -> skipped
                "course": "supply_chain_design", "worked_well": False,
                "issues": [], "topics": [], "one_line": "x", "grade": {},
            },
            "conv-ok": {                     # worked well -> never in meta
                "course": "supply_chain_design", "worked_well": True,
                "issues": [], "topics": [], "one_line": "x", "grade": {},
            },
        },
        "examples": {"exemplary": [], "high_engagement": [], "sample": {}},
        "topics_by_course": {},
    }
    (tmp_path / "2026-04-26.json").write_text(json.dumps(blob), encoding="utf-8")

    body = _login(_app(), MASTER).get("/api/analytics?week=2026-05-01").get_json()
    meta = body["conversation_meta"]
    assert set(meta) == {real_id}            # only the flagged, resolvable id
    entry = meta[real_id]
    assert entry["exercise_kind"] in ("exercise", "practice")
    assert isinstance(entry["message_count"], int)
    assert "exercise_number" in entry and "last_active_at" in entry


def test_flags_are_master_only(seeded, tmp_path, monkeypatch):
    """The "Didn't work well" flags show only in the master view; a course-scoped
    login gets ``all_access: False`` and no flag-bearing conversations at all."""
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    blob = {
        "conversations": {
            "conv-1": {
                "course": "supply_chain_design",
                "worked_well": False,
                "issues": [],
                "topics": [],
                "one_line": "handed it over",
                "grade": {"total_score": 20, "max_score": 40, "overview": "gave it away"},
            }
        },
        "examples": {"exemplary": [], "high_engagement": [], "sample": {}},
        "topics_by_course": {},
    }
    (tmp_path / "2026-04-26.json").write_text(json.dumps(blob), encoding="utf-8")

    # Master sees the flag source and is flagged all-access.
    master = _login(_app(), MASTER).get("/api/analytics?week=2026-05-01").get_json()
    assert master["all_access"] is True
    assert "conv-1" in master["cached"]["conversations"]

    # A scoped login (even to the very course the flag belongs to) gets nothing.
    scoped = _login(_app(), SC_PW).get("/api/analytics?week=2026-05-01").get_json()
    assert scoped["all_access"] is False
    assert scoped["cached"]["conversations"] == {}
