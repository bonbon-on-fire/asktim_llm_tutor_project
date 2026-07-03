"""Student identity (username + password) helpers for main_ui.

Thin wrapper over :mod:`ui_core.services.students`: binds main_ui's own
``Student`` model class to the shared, app-agnostic logic.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from main_ui.db.models import Student
from ui_core.services import students as _shared
from ui_core.services.students import MIN_PASSWORD_LENGTH, WeakPasswordError

# Re-exported unchanged.
__all__ = [
    "MIN_PASSWORD_LENGTH",
    "WeakPasswordError",
    "get_student",
    "create_student",
    "verify_password",
]


def get_student(db: Session, username: str) -> Student | None:
    """Return the Student row for the given username, or None if absent."""
    return _shared.get_student(db, username, student_cls=Student)


def create_student(db: Session, *, username: str, password: str) -> Student:
    """Insert a new students row with the password hashed via bcrypt.

    Raises:
        WeakPasswordError: if ``password`` is shorter than the minimum.
    """
    return _shared.create_student(
        db, username=username, password=password, student_cls=Student
    )


def verify_password(student: Student, password: str) -> bool:
    """Constant-time check that ``password`` matches the stored hash."""
    return _shared.verify_password(student, password)
