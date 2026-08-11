"""Unit tests for scope resolution and session read-back in auth.py."""

from __future__ import annotations

from database_ui.auth import Scope, allowed_courses, mark_authed, resolve_scope
from database_ui.run_app import create_app


def _app(master=None, course_passwords=None):
    app = create_app()
    app.config["DATABASE_UI_PASSWORD"] = master
    app.config["DATABASE_UI_COURSE_PASSWORDS"] = course_passwords or {}
    return app


def test_master_password_resolves_to_all_access():
    app = _app(master="master", course_passwords={"cp": ("supply_chain_design",)})
    with app.test_request_context():
        scope = resolve_scope("master")
        assert scope == Scope(all_access=True, courses=())


def test_course_password_resolves_to_its_courses():
    app = _app(master="master", course_passwords={"cp": ("supply_chain_design",)})
    with app.test_request_context():
        assert resolve_scope("cp") == Scope(all_access=False, courses=("supply_chain_design",))


def test_unknown_password_resolves_to_none():
    app = _app(master="master", course_passwords={"cp": ("x",)})
    with app.test_request_context():
        assert resolve_scope("nope") is None


def test_allowed_courses_reflects_stored_scope():
    app = _app(master="master", course_passwords={"cp": ("supply_chain_design",)})
    with app.test_request_context():
        mark_authed(Scope(all_access=False, courses=("supply_chain_design",)))
        assert allowed_courses() == ["supply_chain_design"]
        mark_authed(Scope(all_access=True, courses=()))
        assert allowed_courses() is None


def test_allowed_courses_is_none_when_no_password_configured():
    app = _app(master=None, course_passwords={})  # open local-dev mode
    with app.test_request_context():
        assert allowed_courses() is None
