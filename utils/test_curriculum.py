"""Standalone tests for utils.curriculum (no pytest dependency).

Run with:
    python -m utils.test_curriculum
"""

from __future__ import annotations

from pathlib import Path
import tempfile

from utils.curriculum import (
    discover_exercises,
    discover_practice,
    practice_exists,
    practice_path,
    read_practice,
)

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def test_discover_practice_filters_and_sorts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Practice problems live in their own practices/ folder.
        prdir = root / "demo" / "practices"
        prdir.mkdir(parents=True)
        (prdir / "practice_02.txt").write_text("p2", encoding="utf-8")
        (prdir / "practice_01.txt").write_text("p1", encoding="utf-8")
        (prdir / "practice_1_bad.txt").write_text("x", encoding="utf-8")
        (prdir / "practice_01.md").write_text("x", encoding="utf-8")
        # Exercises live in exercises/; a stray practice_* there must be ignored
        # by both discoverers (each reads only its own folder).
        exdir = root / "demo" / "exercises"
        exdir.mkdir(parents=True)
        (exdir / "exercise_01.txt").write_text("e1", encoding="utf-8")
        (exdir / "practice_99.txt").write_text("x", encoding="utf-8")

        prac = discover_practice("demo", curriculum_root=root)
        _check("practice sorted + filtered, only practices/", prac == ["01", "02"], f"got {prac}")
        ex = discover_exercises("demo", curriculum_root=root)
        _check("exercises ignore practice_*", ex == ["01"], f"got {ex}")


def test_practice_path_exists_and_read() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        prdir = root / "demo" / "practices"
        prdir.mkdir(parents=True)
        (prdir / "practice_03.txt").write_text("hello practice", encoding="utf-8")

        p = practice_path("demo", "03", curriculum_root=root)
        _check("practice_path points at file", p.name == "practice_03.txt", f"got {p.name}")
        _check("practice_exists true", practice_exists("demo", "03", curriculum_root=root))
        _check("practice_exists false for missing", not practice_exists("demo", "99", curriculum_root=root))
        _check("read_practice returns text", read_practice("demo", "03", curriculum_root=root) == "hello practice")
        _check("read_practice missing -> ''", read_practice("demo", "99", curriculum_root=root) == "")


def main() -> int:
    tests = [
        test_discover_practice_filters_and_sorts,
        test_practice_path_exists_and_read,
    ]
    for t in tests:
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
