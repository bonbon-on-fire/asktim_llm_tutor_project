# Curriculum Archive Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce `curriculum/_archive/` so archived courses vanish from the sandbox picker and are rejected by `validate_course`, while offline tooling still reaches them by explicit slug.

**Architecture:** Active courses stay at `curriculum/<course>/`; archived ones move under `curriculum/_archive/<course>/`. `utils/curriculum.py` becomes the single source of truth: `list_courses()` excludes the archive, and `course_dir()` falls back into it. Visibility is enforced at enumeration and validation, never at path resolution — which is why RAG ingest and eval keep working on archived courses.

**Tech Stack:** Python 3.12, Flask, pathlib. No new dependencies.

## Global Constraints

- Spec: [docs/superpowers/specs/2026-07-21-curriculum-archive-design.md](../specs/2026-07-21-curriculum-archive-design.md)
- Archive folder name is exactly `_archive`, exported as `ARCHIVE_DIRNAME` from `utils.curriculum`. Never hardcode the string outside that module.
- **No course is moved into the archive in this plan.** It ships the mechanism only; the moves are a follow-up. Every task must leave the six existing courses active.
- Tests are standalone `python -m <module>` scripts using the repo's `_check(name, cond, detail)` helper and a `main() -> int` returning 1 on failure. No pytest.
- `list_courses()` takes `curriculum_root` as its **first positional** parameter.
- **Do not modify `rag/test_lecture_index.py`.** Its `_courses_with_index()` globs
  `*/lecture_index.json`, which is single-level, so `_archive/<course>/lecture_index.json`
  never matches and archived courses drop out of that validation test on their own.
  It is the fourth course scanner and is intentionally left alone.
- Git commits omit any `Co-Authored-By` trailer.

---

### Task 1: Archive-aware course listing

**Files:**
- Modify: `utils/curriculum.py:283-288`
- Test: `utils/test_curriculum.py`

**Interfaces:**
- Consumes: `_root(curriculum_root)` (existing, `utils/curriculum.py:31`)
- Produces: `ARCHIVE_DIRNAME: str`, `list_courses(curriculum_root=None) -> list[str]` (active only), `list_archived_courses(curriculum_root=None) -> list[str]`

- [ ] **Step 1: Write the failing tests**

Add to `utils/test_curriculum.py`. Extend the existing import block at the top of the file to include the three new names:

```python
from utils.curriculum import (
    ARCHIVE_DIRNAME,
    TUTOR_RULES_HEADER,
    append_course_tutor_rules,
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
```

Then add these two test functions:

```python
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
```

Register both in `main()` by extending the `tests` list:

```python
    tests = [
        test_discover_practice_filters_and_sorts,
        test_practice_path_exists_and_read,
        test_course_tutor_rules,
        test_pinned_context,
        test_list_courses_excludes_archive,
        test_list_archived_courses_without_archive_folder,
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m utils.test_curriculum`
Expected: `ImportError: cannot import name 'ARCHIVE_DIRNAME' from 'utils.curriculum'`

- [ ] **Step 3: Write the implementation**

First add the constant near the top of the file, immediately after
`_PRACTICE_NAME_RE` at `utils/curriculum.py:22`. It must be bound before
`course_dir` (line 36), which uses it in Task 2:

```python
# Courses under curriculum/_archive/ are retired: hidden from the apps, still
# readable by offline tooling via course_dir(). See
# docs/superpowers/specs/2026-07-21-curriculum-archive-design.md.
ARCHIVE_DIRNAME = "_archive"
```

Then replace `utils/curriculum.py:283-288` (the current `list_courses`) with:

```python
def list_courses(curriculum_root: Path | str | None = None) -> list[str]:
    """Return sorted ACTIVE course folder names under the curriculum root.

    Both the ``_archive`` folder itself and the courses inside it are excluded.
    There is deliberately no ``include_archived`` flag — callers that want the
    retired set call :func:`list_archived_courses` and compose, so no caller can
    leak archived courses by passing a truthy argument.
    """
    root = _root(curriculum_root)
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir() if p.is_dir() and p.name != ARCHIVE_DIRNAME
    )


def list_archived_courses(curriculum_root: Path | str | None = None) -> list[str]:
    """Return sorted course folder names under ``curriculum/_archive/``.

    Empty when the archive folder is absent.
    """
    archive = _root(curriculum_root) / ARCHIVE_DIRNAME
    if not archive.is_dir():
        return []
    return sorted(p.name for p in archive.iterdir() if p.is_dir())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m utils.test_curriculum`
Expected: PASS — the summary line ends `0 failed`, and the new
`test_list_courses_excludes_archive` / `test_list_archived_courses_without_archive_folder`
blocks each print only `PASS` lines. (The passed count is a total of individual
`_check` calls across all tests, so don't assert an exact number.)

- [ ] **Step 5: Verify the real curriculum tree is unchanged**

Run: `python -c "from utils.curriculum import list_courses, list_archived_courses; print(list_courses()); print(list_archived_courses())"`
Expected: all six courses listed as active, `[]` archived:
```
['cities_and_climate_change', 'intro_to_international_development_planning', 'mathematics_for_cs', 'meaning_of_life', 'physics_iii_vibrations_and_waves', 'supply_chain_design']
[]
```

- [ ] **Step 6: Commit**

```bash
git add utils/curriculum.py utils/test_curriculum.py
git commit -m "feat(curriculum): exclude _archive/ from list_courses"
```

---

### Task 2: `course_dir()` resolves archived courses

**Files:**
- Modify: `utils/curriculum.py:36-38`
- Test: `utils/test_curriculum.py`

**Interfaces:**
- Consumes: `ARCHIVE_DIRNAME`, `_root()` from Task 1
- Produces: `course_dir(course, curriculum_root=None) -> Path` with archive fallback. Every existing helper built on it (`exercises_dir`, `practices_dir`, `exercise_path`, `read_pinned_context`, and `rag/store.py:index_dir`) inherits the fallback with no change of its own.

- [ ] **Step 1: Write the failing tests**

Add to `utils/test_curriculum.py`. Extend the import block from Task 1 to also include `course_dir`:

```python
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
```

Then add:

```python
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
```

Register both in `main()`:

```python
    tests = [
        test_discover_practice_filters_and_sorts,
        test_practice_path_exists_and_read,
        test_course_tutor_rules,
        test_pinned_context,
        test_list_courses_excludes_archive,
        test_list_archived_courses_without_archive_folder,
        test_course_dir_resolves_archived,
        test_archived_course_files_still_readable,
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m utils.test_curriculum`
Expected: FAIL — `FAIL  archived course resolves under _archive` and `FAIL  exercise_exists finds an archived exercise`, because `course_dir` still returns `root / course` unconditionally.

- [ ] **Step 3: Write the implementation**

Replace `utils/curriculum.py:36-38` with:

```python
def course_dir(course: str, curriculum_root: Path | str | None = None) -> Path:
    """Return the course folder path, resolving archived courses too.

    Active courses resolve to ``curriculum/<course>/``. A course that exists
    only under ``curriculum/_archive/<course>/`` resolves there, so offline
    tooling (``rag.ingest``, the eval runners) still reaches an archived course
    by slug even though the apps reject it. A slug in neither location returns
    the direct path unchanged, matching the previous behavior for an unknown
    course.

    A slug present in BOTH locations resolves to the active copy. That state is
    an operator mistake, not a supported configuration.
    """
    root = _root(curriculum_root)
    direct = root / course
    if direct.is_dir():
        return direct
    archived = root / ARCHIVE_DIRNAME / course
    return archived if archived.is_dir() else direct
```

`ARCHIVE_DIRNAME` is already bound at `utils/curriculum.py:22` from Task 1, above
this function, so no import-time ordering problem arises.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m utils.test_curriculum`
Expected: PASS — the summary line ends `0 failed`, with all eight test blocks
printing only `PASS` lines.

- [ ] **Step 5: Verify no regression in the real tree**

Run: `python -m utils.test_figures && python -m rag.test_week_scope`
Expected: both suites pass unchanged (they resolve real course paths through `course_dir`).

- [ ] **Step 6: Commit**

```bash
git add utils/curriculum.py utils/test_curriculum.py
git commit -m "feat(curriculum): resolve archived courses via course_dir fallback"
```

---

### Task 3: Both apps hide and reject archived courses

**Files:**
- Modify: `main_ui/routes/_validation.py:27-31`
- Modify: `sandbox_ui/routes/_validation.py:29-33`
- Create: `main_ui/routes/test_validation_archive.py`
- Create: `sandbox_ui/routes/test_validation_archive.py`

**Interfaces:**
- Consumes: `list_courses(curriculum_root)` and `ARCHIVE_DIRNAME` from Task 1
- Produces: no new public names. `_list_courses()` keeps returning `set[str]` in both apps, so `validate_course` and `list_context_options` are untouched.

- [ ] **Step 1: Write the failing tests**

Create `main_ui/routes/test_validation_archive.py`:

```python
"""Standalone test: archived courses are hidden and rejected by validate_course.

Run with:
    python -m main_ui.routes.test_validation_archive
"""

from __future__ import annotations

import shutil

from main_ui.routes import _validation as V
from utils.curriculum import ARCHIVE_DIRNAME

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
    """Assert an archived course is hidden and rejected, and DEFAULT_COURSE is active."""
    course = "tmp_course_archived"
    archived_dir = V._CURRICULUM_DIR / ARCHIVE_DIRNAME / course
    (archived_dir / "exercises").mkdir(parents=True, exist_ok=True)
    (archived_dir / "exercises" / "exercise_1.txt").write_text("BODY", encoding="utf-8")
    try:
        courses = V._list_courses()
        _check("archived course not listed", course not in courses, sorted(courses))
        _check("_archive itself not listed", ARCHIVE_DIRNAME not in courses, sorted(courses))

        failure = V.validate_course(course)
        _check("validate_course rejects archived", failure is not None)
        _check(
            "rejection reason is 'no such course'",
            (failure or {}).get("reason") == "no such course",
            failure,
        )
        # Guard: archiving a course that is still an app default would otherwise
        # break that app silently.
        _check(
            f"DEFAULT_COURSE {V.DEFAULT_COURSE!r} is active",
            V.DEFAULT_COURSE in courses,
            sorted(courses),
        )
    finally:
        shutil.rmtree(archived_dir, ignore_errors=True)
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Create `sandbox_ui/routes/test_validation_archive.py` with the identical body, changing only the docstring run line and the import:

```python
"""Standalone test: archived courses are hidden and rejected by validate_course.

Run with:
    python -m sandbox_ui.routes.test_validation_archive
"""

from __future__ import annotations

import shutil

from sandbox_ui.routes import _validation as V
from utils.curriculum import ARCHIVE_DIRNAME
```

...followed by the same `_PASSED`/`_FAILED`, `_check`, and `main()` as above, plus one extra assertion inserted before the `finally:` block, because sandbox_ui is the app with the picker:

```python
        opts = V.list_context_options()
        slugs = [c["slug"] for c in opts["courses"]]
        _check("picker omits archived course", course not in slugs, slugs)
        _check("picker omits _archive itself", ARCHIVE_DIRNAME not in slugs, slugs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m main_ui.routes.test_validation_archive`
Expected: FAIL — `FAIL  archived course not listed`, because `_list_courses()` still returns every subdirectory including `_archive`.

Run: `python -m sandbox_ui.routes.test_validation_archive`
Expected: FAIL — same, plus `FAIL  picker omits _archive itself`.

- [ ] **Step 3: Write the implementation**

In `main_ui/routes/_validation.py`, add to the existing `utils.curriculum` import block (after line 15):

```python
from utils.curriculum import list_courses as _list_active_courses
```

Then replace `main_ui/routes/_validation.py:27-31` with:

```python
def _list_courses() -> set[str]:
    """Return the set of ACTIVE course directory names under ``curriculum/``.

    Delegates to utils.curriculum so archived courses (under
    ``curriculum/_archive/``) are excluded in exactly one place.
    """
    return set(_list_active_courses(_CURRICULUM_DIR))
```

In `sandbox_ui/routes/_validation.py`, add the same import after line 15's import block, then replace `sandbox_ui/routes/_validation.py:29-33` with:

```python
def _list_courses() -> set[str]:
    """Slugs of all ACTIVE built-in courses (subdirectories of curriculum/).

    Delegates to utils.curriculum so archived courses (under
    ``curriculum/_archive/``) are excluded in exactly one place.
    """
    return set(_list_active_courses(_CURRICULUM_DIR))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m main_ui.routes.test_validation_archive`
Expected: PASS — `5 passed, 0 failed`

Run: `python -m sandbox_ui.routes.test_validation_archive`
Expected: PASS — `7 passed, 0 failed`

- [ ] **Step 5: Verify existing app tests still pass**

Run: `python -m main_ui.routes.test_validation_practice && python -m sandbox_ui.routes.test_validation_practice && python -m main_ui.routes.test_embed_practice && python -m sandbox_ui.routes.test_embed_practice`
Expected: all four report `0 failed`.

- [ ] **Step 6: Commit**

```bash
git add main_ui/routes/_validation.py sandbox_ui/routes/_validation.py main_ui/routes/test_validation_archive.py sandbox_ui/routes/test_validation_archive.py
git commit -m "feat(apps): hide and reject archived courses in both UIs"
```

---

### Task 4: Dev runner, archive scaffolding, and docs

**Files:**
- Modify: `internal_testing/run_transcript.py:41-43` (imports), `:132-136`
- Create: `curriculum/_archive/.gitkeep`
- Modify: `curriculum/README.md`

**Interfaces:**
- Consumes: `list_courses(curriculum_root)` from Task 1
- Produces: nothing consumed by later tasks. This is the final task.

- [ ] **Step 1: Update the dev runner's scanner**

In `internal_testing/run_transcript.py`, add to the import block at line 41-43:

```python
from utils.curriculum import list_courses as _list_active_courses
```

Then replace `internal_testing/run_transcript.py:132-136` with:

```python
def _discover_courses() -> list[str]:
    """Return available ACTIVE course folder names from curriculum/.

    Archived courses (under curriculum/_archive/) are excluded from sweeps that
    iterate every course; pass ``--course <slug>`` to run one explicitly, which
    still resolves via course_dir()'s archive fallback.
    """
    return _list_active_courses(_CURRICULUM_DIR)
```

- [ ] **Step 2: Verify the runner still discovers all six courses**

Run: `python -c "from internal_testing.run_transcript import _discover_courses; print(_discover_courses())"`
Expected:
```
['cities_and_climate_change', 'intro_to_international_development_planning', 'mathematics_for_cs', 'meaning_of_life', 'physics_iii_vibrations_and_waves', 'supply_chain_design']
```

- [ ] **Step 3: Create the archive folder**

```bash
mkdir -p curriculum/_archive
printf '%s\n' "# Archived courses live here — see ../README.md, section \"Archiving a course\"." > curriculum/_archive/.gitkeep
```

- [ ] **Step 4: Document the structure**

In `curriculum/README.md`, inside the ```text structure block, add these two lines immediately after the `rag_index/` line (at the same indent level as `<course_name>/`, i.e. two spaces):

```text
  _archive/                          # archived courses — hidden from the apps, still readable by tooling
    <course_name>/                   # same layout as an active course
```

- [ ] **Step 5: Document the workflow**

In `curriculum/README.md`, add this section immediately after the "Adding a new course" section and before "Adding an exercise to an existing course":

```markdown
## Archiving a course

Archived courses stay in the repo but disappear from the apps: the sandbox
context switcher stops listing them and `validate_course` rejects their slug, so
their embed URLs return 404.

1. Move the folder: `git mv curriculum/<course> curriculum/_archive/<course>`.
2. Confirm no app still defaults to it — `DEFAULT_COURSE` in
   [main_ui/routes/_validation.py](../main_ui/routes/_validation.py) and
   [sandbox_ui/routes/_validation.py](../sandbox_ui/routes/_validation.py). The
   `test_validation_archive` standalone tests assert this.
3. Commit. The course's `rag_index/` moves with it, since the index is a child
   of the course folder.

Existing conversations that reference an archived course still render in
`database_ui` — its display-name map is hardcoded and never reads `curriculum/`.

Offline tooling still reaches an archived course by explicit slug (for example
`python -m rag.ingest --course <archived>`), because `course_dir()` falls back to
`curriculum/_archive/<course>/`. Only discovery and validation change.

To unarchive, move the folder back.
```

- [ ] **Step 6: Note archive state in the course table**

In `curriculum/README.md`, immediately after the "Available courses" table, add:

```markdown
All six courses above are currently **active**. Archived courses, if any, live
under `_archive/` and are listed by `list_archived_courses()` in
[`utils/curriculum.py`](../utils/curriculum.py).
```

- [ ] **Step 7: Run the full standalone suite**

Run each and confirm `0 failed`:
```bash
python -m utils.test_curriculum
python -m main_ui.routes.test_validation_archive
python -m sandbox_ui.routes.test_validation_archive
python -m main_ui.routes.test_validation_practice
python -m sandbox_ui.routes.test_validation_practice
```

- [ ] **Step 8: Confirm no behavior changed for the six live courses**

Run: `python -c "from sandbox_ui.routes._validation import list_context_options; print([c['slug'] for c in list_context_options()['courses']])"`
Expected: all six slugs, unchanged from before this plan.

- [ ] **Step 9: Commit**

```bash
git add internal_testing/run_transcript.py curriculum/_archive/.gitkeep curriculum/README.md
git commit -m "feat(curriculum): scaffold _archive/ and document archiving"
```

---

## Deviation from the spec

The spec's Testing section says tests "build a temporary curriculum root rather
than mutating the real one." That holds for Tasks 1 and 2 (`utils/test_curriculum.py`
uses `tempfile`). It does **not** hold for Task 3: `_CURRICULUM_DIR` is bound at
module import in both apps' `_validation.py`, so an app-level test cannot
redirect it without monkeypatching. Task 3 therefore follows the established repo
pattern from `sandbox_ui/routes/test_validation_practice.py` — create a
temporary course inside the real `curriculum/` tree and remove it in a `finally`
block. The tests remain valid once real courses are archived, because they assert
on a slug they create themselves rather than on the contents of the tree.
