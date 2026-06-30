"""Standalone test: build_assignment_text resolves practice files by kind.

Run with:
    python -m sandbox_ui.services.test_tutor_bridge_practice
"""

from __future__ import annotations

from pathlib import Path

from sandbox_ui.services.tutor_bridge import build_assignment_text

_REPO = Path(__file__).resolve().parents[2]
_CURRICULUM = _REPO / "curriculum"

_PASSED = 0
_FAILED = 0


def _check(name, cond, detail=""):
    global _PASSED, _FAILED
    if cond:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def main() -> int:
    # Use a temp practice file in a real-shaped course dir.
    import tempfile, shutil
    with tempfile.TemporaryDirectory() as tmp:
        course = "tmp_course_practice"
        exdir = _CURRICULUM / course / "exercises"
        exdir.mkdir(parents=True, exist_ok=True)
        (exdir / "exercise_01.txt").write_text("EXERCISE ONE BODY", encoding="utf-8")
        (exdir / "practice_01.txt").write_text("PRACTICE ONE BODY", encoding="utf-8")
        try:
            ex_text = build_assignment_text(course, "01", exercise_kind="exercise")
            pr_text = build_assignment_text(course, "01", exercise_kind="practice")
            _check("exercise kind resolves exercise file", "EXERCISE ONE BODY" in ex_text, ex_text)
            _check("practice kind resolves practice file", "PRACTICE ONE BODY" in pr_text, pr_text)
            _check("default kind is exercise", "EXERCISE ONE BODY" in build_assignment_text(course, "01"))
        finally:
            shutil.rmtree(_CURRICULUM / course, ignore_errors=True)
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
