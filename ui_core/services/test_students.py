"""Standalone tests for ui_core.services.students (no pytest).

Run with:
    python -m ui_core.services.test_students

The helpers are model-agnostic — they take the ``Student`` ORM class as an
argument — so they're tested in ISOLATION on a local Base (ui_core must not
depend on the app packages).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy.orm import DeclarativeBase, Session

from ui_core.db.models_common import StudentMixin
from ui_core.db.session import build_engine
from ui_core.services import students as svc

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    """Record and print a PASS/FAIL for *name* based on *condition*."""
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


class _Base(DeclarativeBase):
    pass


class Student(StudentMixin, _Base):
    pass


def test_create_get_verify() -> None:
    """Check creating a student hashes the password and lookup/verify round-trip correctly."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        eng = build_engine(f"sqlite:///{Path(tmp) / 's.db'}", sqlite_fk=True)
        _Base.metadata.create_all(eng)
        with Session(eng) as s:
            _check(
                "get_student on absent username -> None",
                svc.get_student(s, "nobody", student_cls=Student) is None,
            )

            student = svc.create_student(
                s, username="alice", password="hunter22", student_cls=Student
            )
            s.commit()
            _check("created student has username", student.username == "alice")
            _check(
                "password is hashed, not stored raw",
                student.password_hash != "hunter22",
            )

            fetched = svc.get_student(s, "alice", student_cls=Student)
            _check("get_student returns the row", fetched is not None)

            _check(
                "verify_password accepts correct password",
                svc.verify_password(fetched, "hunter22"),
            )
            _check(
                "verify_password rejects wrong password",
                not svc.verify_password(fetched, "wrong-pass"),
            )
        eng.dispose()


def test_weak_password_rejected() -> None:
    """Check a too-short password raises ``WeakPasswordError`` and inserts no row."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        eng = build_engine(f"sqlite:///{Path(tmp) / 's2.db'}", sqlite_fk=True)
        _Base.metadata.create_all(eng)
        with Session(eng) as s:
            try:
                svc.create_student(
                    s, username="bob", password="short", student_cls=Student
                )
                _check("weak password raises", False, "did not raise")
            except svc.WeakPasswordError:
                _check("weak password raises", True)

            _check(
                "no row was inserted for the rejected student",
                svc.get_student(s, "bob", student_cls=Student) is None,
            )
        eng.dispose()


def test_verify_password_handles_bad_hash() -> None:
    """Check ``verify_password`` returns False (not raises) when the stored hash is malformed."""
    student = Student(username="carol", password_hash="not-a-real-bcrypt-hash")
    _check(
        "verify_password returns False on malformed hash",
        svc.verify_password(student, "whatever") is False,
    )


def main() -> int:
    """Run all tests in this module and return an exit code (1 if any failed)."""
    for t in (
        test_create_get_verify,
        test_weak_password_rejected,
        test_verify_password_handles_bad_hash,
    ):
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
