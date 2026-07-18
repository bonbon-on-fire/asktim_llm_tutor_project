"""Standalone test: main_ui bridge wrapper forwards exercise_kind to build_assignment_text.

Run:
    python -m main_ui.services.test_tutor_bridge_practice
"""
from __future__ import annotations

import shutil
from pathlib import Path

from main_ui.services import tutor_bridge as tb

_CURRICULUM = Path(__file__).resolve().parents[2] / "curriculum"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    course = "tmp_course_mainbridge_practice"
    prdir = _CURRICULUM / course / "practices"
    prdir.mkdir(parents=True, exist_ok=True)
    (prdir / "practice_1.txt").write_text("PRACTICE BODY", encoding="utf-8")
    ok = True
    try:
        text = tb.build_assignment_text(course, "1", exercise_kind="practice")
        ok &= _check("wrapper forwards practice kind", "PRACTICE BODY" in text, text)
    finally:
        shutil.rmtree(_CURRICULUM / course, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
