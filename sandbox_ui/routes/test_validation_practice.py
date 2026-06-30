"""Standalone test for practice options/validation in _validation.

Run with:
    python -m sandbox_ui.routes.test_validation_practice
"""

from __future__ import annotations

from pathlib import Path
import tempfile, shutil

from sandbox_ui.routes import _validation as V

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
    course = "tmp_course_validate_practice"
    exdir = V._CURRICULUM_DIR / course / "exercises"
    exdir.mkdir(parents=True, exist_ok=True)
    (exdir / "practice_01.txt").write_text("PRACTICE BODY", encoding="utf-8")
    try:
        _check("list_practice finds it", V.list_practice(course) == ["01"], V.list_practice(course))
        _check("validate_practice ok", V.validate_practice(course, "01") is None)
        _check("validate_practice missing", V.validate_practice(course, "99") is not None)
        _check("validate_practice bad format", V.validate_practice(course, "1") is not None)
        _check("load_practice_text", V.load_practice_text(course, "01") == "PRACTICE BODY")
        opts = V.list_context_options()
        entry = next((c for c in opts["courses"] if c["slug"] == course), None)
        _check("context_options exposes practice", entry is not None and entry.get("practice") == ["01"], entry)
    finally:
        shutil.rmtree(V._CURRICULUM_DIR / course, ignore_errors=True)
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
