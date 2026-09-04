"""Standalone test for case validation + selection resolution in main_ui.

Run:
    python -m main_ui.routes.test_validation_case
"""
from __future__ import annotations

import shutil

import main_ui.routes._validation as V


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    course = "tmp_course_main_case"
    cdir = V._CURRICULUM_DIR / course / "cases"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "case_1.txt").write_text("CASE BODY", encoding="utf-8")
    exdir = V._CURRICULUM_DIR / course / "exercises"
    exdir.mkdir(parents=True, exist_ok=True)
    (exdir / "exercise_1.txt").write_text("EXERCISE BODY", encoding="utf-8")
    ok = True
    try:
        ok &= _check("validate_case ok", V.validate_case(course, "1") is None)
        ok &= _check("validate_case padded ok", V.validate_case(course, "01") is None)
        ok &= _check("validate_case missing file", V.validate_case(course, "99") is not None)
        ok &= _check("validate_case bad format", V.validate_case(course, "x") is not None)
        ok &= _check("validate_selection case", V.validate_selection(course, "1", "case") is None)

        n, k, err = V.resolve_embed_selection(course, None, None, "1", "01")
        ok &= _check("resolve case", (n, k) == ("1", "case") and err is None, (n, k, err))
        n, k, err = V.resolve_embed_selection(course, "1", None, None, "01")
        ok &= _check("resolve exercise still works", (n, k) == ("1", "exercise") and err is None, (n, k, err))
        n, k, err = V.resolve_embed_selection(course, "1", None, "1", "01")
        ok &= _check("resolve exercise+case -> error", err is not None and n is None, (n, k, err))
    finally:
        shutil.rmtree(V._CURRICULUM_DIR / course, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
