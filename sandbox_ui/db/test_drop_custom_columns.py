"""Test the one-time boot step that drops the removed custom_* columns.

Uses a temp SQLite file; asserts idempotence and fresh-DB no-op.
"""

from __future__ import annotations

import sqlalchemy as sa

from sandbox_ui.run_app import _drop_custom_context_columns

_CUSTOM = [
    "custom_course_text",
    "custom_exercise_text",
    "custom_tutor_prompt",
    "custom_syllabus_text",
    "custom_lectures_text",
]


def _columns(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def test_drops_custom_columns_idempotently(tmp_path):
    """Existing custom_* columns are dropped; re-running is a no-op; fresh DB unaffected."""
    engine = sa.create_engine(f"sqlite:///{tmp_path/'t.db'}")
    with engine.begin() as conn:
        cols = ", ".join(f"{c} TEXT" for c in _CUSTOM)
        conn.execute(sa.text(f"CREATE TABLE conversations (id INTEGER PRIMARY KEY, course TEXT, {cols})"))
    assert set(_CUSTOM).issubset(_columns(engine, "conversations"))

    _drop_custom_context_columns(engine)
    remaining = _columns(engine, "conversations")
    assert not (set(_CUSTOM) & remaining)
    assert "course" in remaining  # untouched

    # Idempotent: second run does not error and changes nothing.
    _drop_custom_context_columns(engine)
    assert not (set(_CUSTOM) & _columns(engine, "conversations"))
