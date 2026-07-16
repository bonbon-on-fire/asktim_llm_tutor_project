"""Standalone tests for utils.curriculum (no pytest dependency).

Run with:
    python -m utils.test_curriculum
"""

from __future__ import annotations

from pathlib import Path
import tempfile

from utils.curriculum import (
    TUTOR_RULES_HEADER,
    append_course_tutor_rules,
    discover_exercises,
    discover_practice,
    practice_exists,
    practice_path,
    read_course_tutor_rules,
    read_practice,
)

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    """Record and print a pass/fail result for the named assertion."""
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def test_discover_practice_filters_and_sorts() -> None:
    """Assert discover_practice numeric-sorts and reads only the practices/ folder."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        # Practice problems live in their own practices/ folder.
        prdir = root / "demo" / "practices"
        prdir.mkdir(parents=True)
        (prdir / "practice_2.txt").write_text("p2", encoding="utf-8")
        (prdir / "practice_1.txt").write_text("p1", encoding="utf-8")
        (prdir / "practice_10.txt").write_text("p10", encoding="utf-8")  # numeric, not lexicographic, sort
        (prdir / "practice_1_bad.txt").write_text("x", encoding="utf-8")  # trailing text -> ignored
        (prdir / "practice_1.md").write_text("x", encoding="utf-8")       # wrong extension -> ignored
        # Exercises live in exercises/; a stray practice_* there must be ignored
        # by both discoverers (each reads only its own folder).
        exdir = root / "demo" / "exercises"
        exdir.mkdir(parents=True)
        (exdir / "exercise_1.txt").write_text("e1", encoding="utf-8")
        (exdir / "practice_99.txt").write_text("x", encoding="utf-8")

        prac = discover_practice("demo", curriculum_root=root)
        _check("practice numeric-sorted + filtered, only practices/", prac == ["1", "2", "10"], f"got {prac}")
        ex = discover_exercises("demo", curriculum_root=root)
        _check("exercises ignore practice_*", ex == ["1"], f"got {ex}")


def test_practice_path_exists_and_read() -> None:
    """Assert practice_path/practice_exists/read_practice work and normalize padded input."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        prdir = root / "demo" / "practices"
        prdir.mkdir(parents=True)
        (prdir / "practice_3.txt").write_text("hello practice", encoding="utf-8")

        p = practice_path("demo", "3", curriculum_root=root)
        _check("practice_path points at file", p.name == "practice_3.txt", f"got {p.name}")
        # Padded input normalizes to the non-padded file.
        _check(
            "practice_path normalizes padded input",
            practice_path("demo", "03", curriculum_root=root).name == "practice_3.txt",
        )
        _check("practice_exists true", practice_exists("demo", "3", curriculum_root=root))
        _check("practice_exists true (padded input normalizes)", practice_exists("demo", "03", curriculum_root=root))
        _check("practice_exists false for missing", not practice_exists("demo", "99", curriculum_root=root))
        _check("read_practice returns text", read_practice("demo", "3", curriculum_root=root) == "hello practice")
        _check("read_practice missing -> ''", read_practice("demo", "99", curriculum_root=root) == "")


def test_course_tutor_rules() -> None:
    """Assert per-course tutor_rules.txt is read and appended (present/absent/empty)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        base = "BASE PROMPT"

        # Absent -> read returns '' and append leaves the base unchanged.
        (root / "no_rules").mkdir(parents=True)
        _check("read missing -> ''", read_course_tutor_rules("no_rules", curriculum_root=root) == "")
        _check(
            "append missing -> base unchanged",
            append_course_tutor_rules(base, "no_rules", curriculum_root=root) == base,
        )

        # Empty / whitespace-only -> treated as absent.
        (root / "empty").mkdir(parents=True)
        (root / "empty" / "tutor_rules.txt").write_text("   \n\t\n", encoding="utf-8")
        _check("read empty -> ''", read_course_tutor_rules("empty", curriculum_root=root) == "")
        _check(
            "append empty -> base unchanged",
            append_course_tutor_rules(base, "empty", curriculum_root=root) == base,
        )

        # Present -> stripped content read; appended under the header.
        (root / "sc").mkdir(parents=True)
        (root / "sc" / "tutor_rules.txt").write_text("\n- Use spreadsheets.\n", encoding="utf-8")
        _check(
            "read present -> stripped",
            read_course_tutor_rules("sc", curriculum_root=root) == "- Use spreadsheets.",
        )
        appended = append_course_tutor_rules(base, "sc", curriculum_root=root)
        _check(
            "append present -> base + header + rules",
            appended == f"{base}\n\n{TUTOR_RULES_HEADER}\n- Use spreadsheets.",
            f"got {appended!r}",
        )

        # Empty course string -> no-op (defensive).
        _check("read '' course -> ''", read_course_tutor_rules("", curriculum_root=root) == "")


def main() -> int:
    """Run all tests and return 1 if any failed, else 0."""
    tests = [
        test_discover_practice_filters_and_sorts,
        test_practice_path_exists_and_read,
        test_course_tutor_rules,
    ]
    for t in tests:
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
