"""Standalone tests for utils.curriculum (no pytest dependency).

Run with:
    python -m utils.test_curriculum
"""

from __future__ import annotations

from pathlib import Path
import tempfile

from rag.sources import load_local_docs
from rag.store import index_dir
from utils.curriculum import (
    ARCHIVE_DIRNAME,
    TUTOR_RULES_HEADER,
    append_course_tutor_rules,
    course_dir,
    discover_exercises,
    discover_practice,
    exercise_exists,
    list_archived_courses,
    list_courses,
    practice_exists,
    practice_path,
    read_course_tutor_rules,
    read_pinned_context,
    read_practice,
)
from utils.figures import discover_figures
from utils.lectures import load_lecture_transcripts

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


def test_pinned_context() -> None:
    """Assert read_pinned_context joins all pinned/*.txt (absent/empty/multiple)."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # No pinned/ folder -> ''.
        (root / "bare").mkdir(parents=True)
        _check("no pinned/ folder -> ''", read_pinned_context("bare", curriculum_root=root) == "")

        # Multiple files -> sorted by name, stripped, joined with a blank line;
        # empty/whitespace-only files skipped.
        pdir = root / "sc" / "pinned"
        pdir.mkdir(parents=True)
        (pdir / "b_second.txt").write_text("  Second doc.\n", encoding="utf-8")
        (pdir / "a_first.txt").write_text("First doc.", encoding="utf-8")
        (pdir / "c_empty.txt").write_text("   \n", encoding="utf-8")  # skipped
        (pdir / "note.md").write_text("ignored — wrong extension", encoding="utf-8")
        got = read_pinned_context("sc", curriculum_root=root)
        _check(
            "pinned docs sorted + joined, empties/non-txt skipped",
            got == "First doc.\n\nSecond doc.",
            f"got {got!r}",
        )

        # Empty course string -> '' (defensive).
        _check("read '' course -> ''", read_pinned_context("", curriculum_root=root) == "")


def test_list_courses_excludes_archive() -> None:
    """Assert list_courses hides _archive and its children, and the two sets are disjoint."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "active_course").mkdir()
        (root / "another_active").mkdir()
        (root / ARCHIVE_DIRNAME / "old_course").mkdir(parents=True)
        (root / ARCHIVE_DIRNAME / "older_course").mkdir(parents=True)
        (root / "README.md").write_text("not a course", encoding="utf-8")

        active = list_courses(root)
        _check("_archive itself is not a course", ARCHIVE_DIRNAME not in active, active)
        _check(
            "archived children excluded from active",
            active == ["active_course", "another_active"],
            active,
        )

        archived = list_archived_courses(root)
        _check(
            "list_archived_courses returns _archive children",
            archived == ["old_course", "older_course"],
            archived,
        )
        _check("active and archived are disjoint", set(active).isdisjoint(archived))


def test_list_archived_courses_without_archive_folder() -> None:
    """Assert an absent _archive/ yields [] and does not disturb list_courses."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "solo").mkdir()
        _check("absent _archive -> []", list_archived_courses(root) == [])
        _check("list_courses unaffected", list_courses(root) == ["solo"], list_courses(root))


def test_course_dir_resolves_archived() -> None:
    """Assert course_dir falls back to _archive/ and prefers active on collision."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "live_course").mkdir()
        (root / ARCHIVE_DIRNAME / "old_course").mkdir(parents=True)
        # Same slug in both places: an operator mistake, but must resolve
        # deterministically to the active copy.
        (root / "both").mkdir()
        (root / ARCHIVE_DIRNAME / "both").mkdir(parents=True)

        _check(
            "active course resolves directly",
            course_dir("live_course", root) == root / "live_course",
            course_dir("live_course", root),
        )
        _check(
            "archived course resolves under _archive",
            course_dir("old_course", root) == root / ARCHIVE_DIRNAME / "old_course",
            course_dir("old_course", root),
        )
        _check(
            "collision prefers the active copy",
            course_dir("both", root) == root / "both",
            course_dir("both", root),
        )
        _check(
            "unknown slug returns the direct path unchanged",
            course_dir("ghost", root) == root / "ghost",
            course_dir("ghost", root),
        )


def test_archived_course_files_still_readable() -> None:
    """Assert helpers built on course_dir reach an archived course's content."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        exdir = root / ARCHIVE_DIRNAME / "old_course" / "exercises"
        exdir.mkdir(parents=True)
        (exdir / "exercise_1.txt").write_text("BODY", encoding="utf-8")

        _check(
            "exercise_exists finds an archived exercise",
            exercise_exists("old_course", "1", curriculum_root=root),
        )
        _check(
            "discover_exercises lists an archived exercise",
            discover_exercises("old_course", curriculum_root=root) == ["1"],
            discover_exercises("old_course", curriculum_root=root),
        )


def test_archived_course_reachable_by_all_helpers() -> None:
    """Assert lectures, figures, RAG sources, and the index dir all resolve into _archive/."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        base = root / ARCHIVE_DIRNAME / "old_course"
        (base / "lectures").mkdir(parents=True)
        (base / "lectures" / "lecture_1_0_intro.txt").write_text(
            "LECTURE BODY", encoding="utf-8"
        )
        (base / "figures").mkdir()
        (base / "figures" / "exercise_4_map.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        (base / "key_concepts.txt").write_text("KEY CONCEPTS BODY", encoding="utf-8")

        _check(
            "lectures resolve for an archived course",
            "LECTURE BODY" in load_lecture_transcripts("old_course", root),
            load_lecture_transcripts("old_course", root),
        )
        figs = discover_figures("old_course", "4", root)
        _check(
            "figures resolve for an archived course",
            [p.name for p in figs] == ["exercise_4_map.png"],
            figs,
        )
        docs = load_local_docs("old_course", root)
        _check(
            "RAG sources resolve for an archived course",
            any("KEY CONCEPTS BODY" in text for _label, text in docs),
            docs,
        )
        _check(
            "index_dir points inside _archive for an archived course",
            index_dir("old_course", root) == base / "rag_index",
            index_dir("old_course", root),
        )


def test_active_course_paths_unchanged() -> None:
    """Assert the same helpers still resolve an ACTIVE course to its top-level path."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        base = root / "live_course"
        (base / "lectures").mkdir(parents=True)
        (base / "lectures" / "lecture_1_0_intro.txt").write_text(
            "ACTIVE LECTURE", encoding="utf-8"
        )
        _check(
            "active lectures still resolve to the top-level path",
            "ACTIVE LECTURE" in load_lecture_transcripts("live_course", root),
        )
        _check(
            "active index_dir still resolves to the top-level path",
            index_dir("live_course", root) == base / "rag_index",
            index_dir("live_course", root),
        )


def main() -> int:
    """Run all tests and return 1 if any failed, else 0."""
    tests = [
        test_discover_practice_filters_and_sorts,
        test_practice_path_exists_and_read,
        test_course_tutor_rules,
        test_pinned_context,
        test_list_courses_excludes_archive,
        test_list_archived_courses_without_archive_folder,
        test_course_dir_resolves_archived,
        test_archived_course_files_still_readable,
        test_archived_course_reachable_by_all_helpers,
        test_active_course_paths_unchanged,
    ]
    for t in tests:
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
