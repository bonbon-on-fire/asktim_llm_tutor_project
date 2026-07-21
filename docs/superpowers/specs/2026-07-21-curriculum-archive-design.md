# Curriculum archive infrastructure

**Date:** 2026-07-21
**Status:** Approved, not yet implemented

## Problem

The sandbox context switcher lists every course, including ones we no longer
use, which makes the picker noisy for anyone we hand the tool to. There is no
archive / hide / active flag to hook into: courses are not database rows, they
are folders under `curriculum/`, and every scanner lists all subdirectories it
finds. Adding this means introducing a visibility mechanism, not flipping an
existing one.

## Goals

- Archived courses disappear from the sandbox picker and are rejected as course
  options in both apps.
- Course state is visible from a directory listing.
- Offline tooling (RAG ingest, eval runners) can still reach an archived course
  by explicit slug.
- Existing conversations referencing an archived course keep rendering.

## Non-goals

- Moving any course into the archive. This change ships the mechanism only;
  the moves land in a follow-up.
- A per-course metadata system, deployment targets, or display ordering.
- Access control or faculty roles (tracked separately in the 07/21 notes).

## Chosen approach

Archived courses move into a single `curriculum/_archive/` folder. Active
courses stay exactly where they are.

```text
curriculum/
  README.md
  about_asktim.txt
  supply_chain_design/          # active — path unchanged
  cities_and_climate_change/    # active — path unchanged
  _archive/
    mathematics_for_cs/         # hidden from apps
```

Because active course paths never change, `course_dir()`, the per-course
`rag_index/`, and every direct path build in `eval/` keep working untouched. An
archived course becomes unreachable by its normal path, which is what archived
means.

### Alternatives rejected

- **Both `active/` and `archive/` folders.** Most explicit, but it changes every
  active course's path, so `course_dir()`, `rag/store.py:index_dir()`,
  `main_ui`'s direct `load_course_name()` read, and the `eval/rag_judge` scripts
  that build `curriculum/<course>/lectures` by hand all need fixing. It also
  churns six `rag_index/vectors.npy` binaries through a git move.
- **Marker file (`curriculum/<course>/.archived`).** Smallest blast radius, but
  `ls curriculum/` no longer shows course state, losing the readability that
  motivated the request.

## Design

### 1. Single source of truth

`utils/curriculum.py` owns the mechanism. Its `list_courses()` currently has no
production callers, so it can change freely.

```python
ARCHIVE_DIRNAME = "_archive"

def list_courses(curriculum_root=None) -> list[str]:
    """Active course slugs. Archived courses live under _archive/ and are excluded."""
    root = _root(curriculum_root)
    if not root.is_dir():
        return []
    return sorted(
        p.name for p in root.iterdir()
        if p.is_dir() and p.name != ARCHIVE_DIRNAME
    )

def list_archived_courses(curriculum_root=None) -> list[str]:
    """Slugs under curriculum/_archive/, sorted. Empty when the folder is absent."""
```

`list_courses()` returns active courses only. Callers wanting both compose the
two functions; there is no `include_archived` flag, so a caller can never
accidentally leak archived courses by passing a truthy argument.

### 2. `course_dir()` resolves archived courses by slug

```python
def course_dir(course, curriculum_root=None) -> Path:
    """Active courses resolve directly; archived ones resolve under _archive/,
    so RAG ingest and eval still work by explicit slug. Returns the direct
    (non-existent) path when the course exists in neither location, matching
    today's behavior for an unknown slug."""
```

Every path helper (`exercises_dir()`, `pinned/`, `rag/store.py:index_dir()`) is
built on `course_dir()`, so this single change keeps all offline tooling working
against archived courses while the apps still reject them at the gate.

This is the load-bearing decision. It implements "hidden from user-facing
surfaces only": visibility is enforced at enumeration and validation, not at
path resolution.

### 3. Consolidating the scanners

Four independent implementations exist today. Three delegate to
`utils.curriculum.list_courses()`:

| File | Function | Change |
|---|---|---|
| `main_ui/routes/_validation.py:27` | `_list_courses()` | Delegate |
| `sandbox_ui/routes/_validation.py:29` | `_list_courses()` | Delegate |
| `internal_testing/run_transcript.py:132` | `_discover_courses()` | Delegate |
| `rag/test_lecture_index.py:19` | `_courses_with_index()` | **None needed** |

`rag/test_lecture_index.py` globs `*/lecture_index.json`, which is single-level,
so `_archive/<course>/lecture_index.json` does not match and archived courses
drop out of that validation test automatically.

### 4. Resulting behavior

| Surface | Archived course |
|---|---|
| Sandbox picker | Gone — `list_context_options()` loops `list_courses()` |
| `validate_course()`, both apps | `"no such course"`; embed URLs return 400 |
| Old transcripts in `database_ui` | Still render — its `COURSE_DISPLAY_NAMES` map is hardcoded and never reads `curriculum/` |
| `rag.ingest --course <archived>` | Still works |
| `internal_testing` sweeps over all courses | Skips archived; explicit `--course` still works |

Archiving a course does **not** migrate or invalidate `conversations.course`
rows. The slug stays the stored identifier; only discovery changes.

### 5. Error handling

- An archived slug fails at `validate_course()` with the existing
  `"no such course"` reason. No new error type, no new UI copy.
- A slug present in neither location behaves exactly as today.
- A course folder that exists in both `curriculum/<course>/` and
  `curriculum/_archive/<course>/` resolves to the active one. This is an
  operator mistake, not a supported state; the archive test asserts the two sets
  are disjoint so it fails loudly in CI.

## Testing

Added to the existing `utils/test_curriculum.py`:

- `_archive` is never returned as a course by `list_courses()`.
- Courses inside `_archive/` are excluded from `list_courses()` and returned by
  `list_archived_courses()`.
- `course_dir()` resolves an archived slug to its `_archive/` path.
- `course_dir()` prefers the active path when a slug exists in both.
- Active and archived course sets are disjoint.

Added to each app's validation tests:

- `validate_course()` rejects an archived slug.
- `DEFAULT_COURSE` is in `list_courses()` — guards against archiving a course
  that is still some app's default, which would otherwise break silently.

Tests build a temporary curriculum root rather than mutating the real one, so
they stay valid once real courses are archived in the follow-up.

## Documentation

`curriculum/README.md` gains:

- An `_archive/` entry in the structure block.
- An "Archiving a course" section: move the folder, confirm no app's
  `DEFAULT_COURSE` points at it, commit.
- A note on the "Available courses" table distinguishing active from archived.

## Rollout

1. This change: mechanism, tests, docs. `_archive/` ships with a `.gitkeep`.
   No behavior change, because no course is archived yet.
2. Follow-up: move the chosen courses into `_archive/`. Which courses is still
   open — the 07/21 action item reads "archive old courses which don't follow
   and use current AskTIM structure."
