"""Unit tests for parsing DATABASE_UI_COURSE_PASSWORDS."""

from __future__ import annotations

from database_ui.config import parse_course_passwords


def test_parse_valid_entries():
    raw = '[{"password": "p1", "courses": ["a", "b"]}, {"password": "p2", "courses": ["c"]}]'
    assert parse_course_passwords(raw) == {"p1": ("a", "b"), "p2": ("c",)}


def test_none_and_empty_yield_empty_map():
    assert parse_course_passwords(None) == {}
    assert parse_course_passwords("") == {}
    assert parse_course_passwords("   ") == {}


def test_malformed_json_fails_safe_to_empty():
    assert parse_course_passwords("not json") == {}
    assert parse_course_passwords('{"password": "p"}') == {}  # object, not a list


def test_bad_entries_are_skipped():
    raw = (
        '[{"password": "", "courses": ["a"]},'          # empty password -> skip
        ' {"courses": ["b"]},'                           # no password -> skip
        ' {"password": "nostr", "courses": []},'         # no courses -> skip
        ' {"password": "ok", "courses": ["c", "", "d"]}]'  # empty course dropped
    )
    assert parse_course_passwords(raw) == {"ok": ("c", "d")}
