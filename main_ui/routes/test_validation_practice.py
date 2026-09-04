"""Standalone test for practice validation + selection resolution in main_ui.

Run:
    python -m main_ui.routes.test_validation_practice
"""
from __future__ import annotations

import shutil

import main_ui.routes._validation as V


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    course = "tmp_course_main_practice"
    prdir = V._CURRICULUM_DIR / course / "practices"
    prdir.mkdir(parents=True, exist_ok=True)
    (prdir / "practice_1.txt").write_text("PRACTICE BODY", encoding="utf-8")
    exdir = V._CURRICULUM_DIR / course / "exercises"
    exdir.mkdir(parents=True, exist_ok=True)
    (exdir / "exercise_1.txt").write_text("EXERCISE BODY", encoding="utf-8")
    ok = True
    try:
        ok &= _check("validate_practice ok", V.validate_practice(course, "1") is None)
        ok &= _check("validate_practice padded ok", V.validate_practice(course, "01") is None)
        ok &= _check("validate_practice missing file", V.validate_practice(course, "99") is not None)
        ok &= _check("validate_practice bad format", V.validate_practice(course, "x") is not None)
        ok &= _check("validate_selection practice", V.validate_selection(course, "1", "practice") is None)
        ok &= _check("validate_selection exercise", V.validate_selection(course, "1", "exercise") is None)

        n, k, err = V.resolve_embed_selection(course, None, "1", None, "01")
        ok &= _check("resolve practice", (n, k) == ("1", "practice") and err is None, (n, k, err))
        n, k, err = V.resolve_embed_selection(course, "1", None, None, "01")
        ok &= _check("resolve exercise", (n, k) == ("1", "exercise") and err is None, (n, k, err))
        n, k, err = V.resolve_embed_selection(course, None, None, None, "1")
        ok &= _check("resolve default exercise", (n, k) == ("1", "exercise") and err is None, (n, k, err))
        n, k, err = V.resolve_embed_selection(course, "1", "1", None, "01")
        ok &= _check("resolve both -> error", err is not None and n is None, (n, k, err))
    finally:
        shutil.rmtree(V._CURRICULUM_DIR / course, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
