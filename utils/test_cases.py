"""Standalone test for the `case` problem kind in utils.curriculum.

Run:
    python -m utils.test_cases
"""
from __future__ import annotations

import shutil

import utils.curriculum as C


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    root = C._DEFAULT_CURRICULUM_ROOT
    course = "tmp_course_cases"
    cdir = root / course / "cases"
    sdir = root / course / "cases_solutions"
    cdir.mkdir(parents=True, exist_ok=True)
    sdir.mkdir(parents=True, exist_ok=True)
    (cdir / "case_1.txt").write_text("CASE BODY", encoding="utf-8")
    (cdir / "case_10.txt").write_text("CASE TEN", encoding="utf-8")
    (sdir / "case_solution_1.txt").write_text("TEACHING NOTE", encoding="utf-8")
    try:
        ok &= _check("case_path non-padded", C.case_path(course, "01").name == "case_1.txt")
        ok &= _check("case_exists true", C.case_exists(course, "1") is True)
        ok &= _check("case_exists padded true", C.case_exists(course, "01") is True)
        ok &= _check("case_exists false", C.case_exists(course, "99") is False)
        ok &= _check("read_case", C.read_case(course, "1") == "CASE BODY")
        ok &= _check("discover_cases sorted numerically", C.discover_cases(course) == ["1", "10"], C.discover_cases(course))
        ok &= _check(
            "solution_path case",
            C.solution_path(course, "1", "case").name == "case_solution_1.txt",
        )
        ok &= _check("read_solution case", C.read_solution(course, "1", "case") == "TEACHING NOTE")
        ok &= _check(
            "problem_path dispatch case",
            C.problem_path(course, "1", "case") == C.case_path(course, "1"),
        )
        ok &= _check(
            "problem_path dispatch exercise (default)",
            C.problem_path(course, "1") == C.exercise_path(course, "1"),
        )
        ok &= _check("ui label for case", C.load_ui_labels(course)["case"] == "Case {n}")
    finally:
        shutil.rmtree(root / course, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
