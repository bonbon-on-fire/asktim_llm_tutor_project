"""Test the one-time boot step that drops retired Conversation columns.

Uses a temp SQLite file; asserts idempotence and fresh-DB no-op.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from sandbox_ui.run_app import _drop_retired_columns

_CUSTOM = [
    "custom_course_text",
    "custom_exercise_text",
    "custom_tutor_prompt",
    "custom_syllabus_text",
    "custom_lectures_text",
]

# The include-toggles retired when course.txt/syllabus.txt moved into
# curriculum/<course>/pinned/ (always in context, so the flags mean nothing).
_TOGGLES = ["course_enabled", "syllabus_enabled"]

_RETIRED = _CUSTOM + _TOGGLES


def _columns(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def test_drops_retired_columns_idempotently(tmp_path):
    """Existing retired columns are dropped; re-running is a no-op; fresh DB unaffected."""
    engine = sa.create_engine(f"sqlite:///{tmp_path/'t.db'}")
    with engine.begin() as conn:
        cols = ", ".join(
            f"{c} TEXT" if c in _CUSTOM else f"{c} BOOLEAN NOT NULL" for c in _RETIRED
        )
        conn.execute(
            sa.text(
                "CREATE TABLE conversations "
                f"(id INTEGER PRIMARY KEY, course TEXT, lectures_enabled BOOLEAN, {cols})"
            )
        )
    assert set(_RETIRED).issubset(_columns(engine, "conversations"))

    _drop_retired_columns(engine)
    remaining = _columns(engine, "conversations")
    assert not (set(_RETIRED) & remaining)
    assert "course" in remaining  # untouched
    assert "lectures_enabled" in remaining  # the surviving toggle is never dropped

    # Idempotent: second run does not error and changes nothing.
    _drop_retired_columns(engine)
    assert not (set(_RETIRED) & _columns(engine, "conversations"))


def test_insert_succeeds_after_dropping_not_null_toggle(tmp_path):
    """Regression: a live DB carrying NOT NULL syllabus_enabled rejected every new
    conversation, because the model no longer supplies that column.

    Reproduces the production 500 (NotNullViolation on POST /api/chat) that this
    boot step exists to clear.
    """
    engine = sa.create_engine(f"sqlite:///{tmp_path/'t.db'}")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE conversations ("
                "id INTEGER PRIMARY KEY, course TEXT, "
                "syllabus_enabled BOOLEAN NOT NULL)"
            )
        )

    # Before the drop: the model's INSERT (which omits syllabus_enabled) is rejected.
    insert = sa.text("INSERT INTO conversations (id, course) VALUES (1, 'cities')")
    with pytest.raises(sa.exc.IntegrityError):
        with engine.begin() as conn:
            conn.execute(insert)

    _drop_retired_columns(engine)

    # After: the same INSERT lands.
    with engine.begin() as conn:
        conn.execute(insert)
        assert conn.execute(sa.text("SELECT count(*) FROM conversations")).scalar() == 1
