"""Standalone test: archived courses are hidden and rejected by validate_course.

Run with:
    python -m main_ui.routes.test_validation_archive
"""

from __future__ import annotations

import shutil

from main_ui.routes import _validation as V
from utils.curriculum import ARCHIVE_DIRNAME

_PASSED = 0
_FAILED = 0


def _check(name, cond, detail=""):
    """Record a pass/fail for a named assertion and print the result."""
    global _PASSED, _FAILED
    if cond:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def main() -> int:
    """Assert a course is visible+accepted while active, then hidden+rejected once archived."""
    course = "tmp_course_archived"
    active_dir = V._CURRICULUM_DIR / course
    archived_dir = V._CURRICULUM_DIR / ARCHIVE_DIRNAME / course
    (active_dir / "exercises").mkdir(parents=True, exist_ok=True)
    (active_dir / "exercises" / "exercise_1.txt").write_text("BODY", encoding="utf-8")
    try:
        # Active phase: prove the scanner genuinely sees this slug before it's archived.
        courses = V._list_courses()
        _check("active course is listed", course in courses, sorted(courses))
        _check("validate_course accepts active", V.validate_course(course) is None)

        # Archive phase: move the same folder and prove the transition hides/rejects it.
        shutil.move(str(active_dir), str(archived_dir))

        courses = V._list_courses()
        _check("archived course not listed", course not in courses, sorted(courses))
        _check("_archive itself not listed", ARCHIVE_DIRNAME not in courses, sorted(courses))

        failure = V.validate_course(course)
        _check("validate_course rejects archived", failure is not None)
        _check(
            "rejection reason is 'no such course'",
            (failure or {}).get("reason") == "no such course",
            failure,
        )
        # Guard: archiving a course that is still an app default would otherwise
        # break that app silently.
        _check(
            f"DEFAULT_COURSE {V.DEFAULT_COURSE!r} is active",
            V.DEFAULT_COURSE in courses,
            sorted(courses),
        )
    finally:
        shutil.rmtree(active_dir, ignore_errors=True)
        shutil.rmtree(archived_dir, ignore_errors=True)
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
