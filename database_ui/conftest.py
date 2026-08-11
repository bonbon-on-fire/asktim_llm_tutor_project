"""Pytest fixtures for database_ui tests.

Points database_ui at a throwaway on-disk SQLite DB *before* importing anything
from database_ui — the engine is built at import time from
``DATABASE_UI_DATABASE_URL`` (see ``database_ui/db/session.py``). This app never
creates schema in production (it only reads the live DB), so tests create the
tables themselves via ``Base.metadata.create_all`` on the throwaway DB.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone

import pytest

_tmp_db = tempfile.NamedTemporaryFile(prefix="database_ui_test_", suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_UI_DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ.setdefault("DATABASE_UI_PASSWORD", "test-password")

from database_ui.db.models import (  # noqa: E402
    Base,
    Conversation,
    Message,
    UploadedFile,
    UploadedImage,
)
from database_ui.db.session import SessionLocal, engine  # noqa: E402

Base.metadata.create_all(engine)


@pytest.fixture()
def db_session():
    """A SQLAlchemy session on the throwaway DB, wiped clean before each test."""
    session = SessionLocal()
    # Clean slate: delete in FK-safe order.
    session.query(UploadedImage).delete()
    session.query(UploadedFile).delete()
    session.query(Message).delete()
    session.query(Conversation).delete()
    session.commit()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _dt(day: int) -> datetime:
    return datetime(2026, 5, day, 12, 0, tzinfo=timezone.utc)


def seed(session) -> dict:
    """Insert a known fixture graph and return ids for assertions.

    Two courses. supply_chain_design has exercises "1" and "2"; meaning_of_life
    has exercise "1". One conversation each; supply_chain ex "1" has a 2-message
    transcript (student turn + tutor turn) with one image and one file attachment
    on the student turn.
    """
    sc = Conversation(
        id=uuid.uuid4(), session_id="s1", username="stu@mit.edu",
        course="supply_chain_design", exercise_number="1", exercise_kind="exercise",
        focus_problem=None, tutor_prompt="p", started_at=_dt(1), last_active_at=_dt(3),
    )
    sc2 = Conversation(
        id=uuid.uuid4(), session_id="s2", username=None,
        course="supply_chain_design", exercise_number="2", exercise_kind="practice",
        focus_problem=4, tutor_prompt="p", started_at=_dt(1), last_active_at=_dt(2),
    )
    mol = Conversation(
        id=uuid.uuid4(), session_id="s3", username="stu@mit.edu",
        course="meaning_of_life", exercise_number="1", exercise_kind="exercise",
        focus_problem=None, tutor_prompt="p", started_at=_dt(1), last_active_at=_dt(1),
    )
    session.add_all([sc, sc2, mol])
    session.flush()

    m_student = Message(
        conversation_id=sc.id, turn=1, role="student", content="hello, comma, and\nnewline",
        pedagogical_reasoning=None, rating=0, cost_usd=None, usage_json=None,
        retrieved_context=None, created_at=_dt(3),
    )
    m_tutor = Message(
        conversation_id=sc.id, turn=1, role="tutor", content="answer",
        pedagogical_reasoning="because", rating=1, cost_usd=0.0123,
        usage_json='{"model": "gpt-5.4-2026-03-05", "input_tokens": 10}',
        retrieved_context='[{"source": "local:sc/ch1", "score": 0.9, "chars": 5, "text": "abcde"}]',
        created_at=_dt(3),
    )
    session.add_all([m_student, m_tutor])
    session.flush()
    session.add(UploadedImage(
        message_id=m_student.id, filename="f.png", mime_type="image/png",
        size_bytes=3, data=b"abc", created_at=_dt(3),
    ))
    session.add(UploadedFile(
        message_id=m_student.id, filename="data.csv", kind="csv",
        extracted_text="col1,col2\n1,2", size_bytes=12, data=b"col1,col2\n1,2",
        created_at=_dt(3),
    ))
    session.commit()
    return {"sc_id": sc.id, "sc2_id": sc2.id, "mol_id": mol.id,
            "m_student_id": m_student.id, "m_tutor_id": m_tutor.id}
