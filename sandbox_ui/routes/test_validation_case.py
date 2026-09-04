"""Standalone test for case options/validation in sandbox_ui _validation.

Run with:
    python -m sandbox_ui.routes.test_validation_case
"""

from __future__ import annotations

import shutil

from sandbox_ui.routes import _validation as V

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
    """Assert case listing, validation, resolution, and context options work for a temp course."""
    course = "tmp_course_validate_case"
    cdir = V._CURRICULUM_DIR / course / "cases"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "case_1.txt").write_text("CASE BODY", encoding="utf-8")
    try:
        _check("list_cases finds it", V.list_cases(course) == ["1"], V.list_cases(course))
        _check("validate_case ok", V.validate_case(course, "1") is None)
        _check("validate_case ok (padded normalizes)", V.validate_case(course, "01") is None)
        _check("validate_case missing", V.validate_case(course, "99") is not None)
        _check("validate_case bad format", V.validate_case(course, "x") is not None)
        _check("validate_selection case", V.validate_selection(course, "1", "case") is None)

        n, k, err = V.resolve_embed_selection(course, None, None, "1", "01")
        _check("resolve case", (n, k) == ("1", "case") and err is None, (n, k, err))
        n, k, err = V.resolve_embed_selection(course, "1", None, "1", "01")
        _check("resolve exercise+case -> error", err is not None and n is None, (n, k, err))

        preview = V.load_selection_preview(course, "1", "case")
        _check("case preview reads body", preview.get("text") == "CASE BODY", preview)

        opts = V.list_context_options()
        entry = next((c for c in opts["courses"] if c["slug"] == course), None)
        _check("context_options exposes cases", entry is not None and entry.get("cases") == ["1"], entry)
    finally:
        shutil.rmtree(V._CURRICULUM_DIR / course, ignore_errors=True)
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
