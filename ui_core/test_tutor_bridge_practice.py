"""Standalone test: the base TutorBridge resolves practice files by kind.

Run:
    python -m ui_core.test_tutor_bridge_practice
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ui_core.tutor_bridge import TutorBridge

_CURRICULUM = Path(__file__).resolve().parents[1] / "curriculum"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    course = "tmp_course_base_practice"
    exdir = _CURRICULUM / course / "exercises"
    prdir = _CURRICULUM / course / "practices"
    exdir.mkdir(parents=True, exist_ok=True)
    prdir.mkdir(parents=True, exist_ok=True)
    (exdir / "exercise_1.txt").write_text("EXERCISE ONE BODY", encoding="utf-8")
    (prdir / "practice_1.txt").write_text("PRACTICE ONE BODY", encoding="utf-8")
    ok = True
    try:
        bridge = TutorBridge()
        ex_text = bridge.build_assignment_text(course, "1", exercise_kind="exercise")
        pr_text = bridge.build_assignment_text(course, "1", exercise_kind="practice")
        ok &= _check("exercise kind resolves exercise file", "EXERCISE ONE BODY" in ex_text, ex_text)
        ok &= _check("practice kind resolves practice file", "PRACTICE ONE BODY" in pr_text, pr_text)
        ok &= _check("default kind is exercise", "EXERCISE ONE BODY" in bridge.build_assignment_text(course, "1"))
        k_ex = bridge.cache_key("tutor_07", course, "1", exercise_kind="exercise")
        k_pr = bridge.cache_key("tutor_07", course, "1", exercise_kind="practice")
        ok &= _check("cache_key differs by kind", k_ex != k_pr, f"{k_ex} == {k_pr}")
    finally:
        shutil.rmtree(_CURRICULUM / course, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
