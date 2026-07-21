"""Canonical curriculum path resolution shared across runners and web apps.

Exercise prompts live under ``curriculum/<course>/exercises/exercise_<N>.txt``
(a subfolder, consistent with ``figures/`` and ``lectures/``). Previously they
sat loose at the top of the course folder; this module is the single place that
knows the layout, so the six call sites that used to duplicate
``course_dir / f"exercise_{n}.txt"`` now share one resolver.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CURRICULUM_ROOT = _REPO_ROOT / "curriculum"

# exercise_<N>.txt — one or more digits, not zero-padded (e.g. exercise_1, exercise_10).
_EXERCISE_NAME_RE = re.compile(r"^exercise_(\d+)\.txt$")

# practice_<N>.txt — one or more digits (parallel to exercises).
_PRACTICE_NAME_RE = re.compile(r"^practice_(\d+)\.txt$")

# Courses under curriculum/_archive/ are retired: hidden from the apps, still
# readable by offline tooling via course_dir(). See
# docs/superpowers/specs/2026-07-21-curriculum-archive-design.md.
ARCHIVE_DIRNAME = "_archive"


def _norm_num(num: str) -> str:
    """Normalize an item number to its non-padded form ('01' -> '1'); pass through non-numeric."""
    s = str(num).strip()
    return str(int(s)) if s.isdigit() else s


def _root(curriculum_root: Path | str | None) -> Path:
    """Return the curriculum root as a Path, falling back to the default when None."""
    return Path(curriculum_root) if curriculum_root is not None else _DEFAULT_CURRICULUM_ROOT


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


def exercises_dir(course: str, curriculum_root: Path | str | None = None) -> Path:
    """Return the exercises folder path (``curriculum/<course>/exercises/``)."""
    return course_dir(course, curriculum_root) / "exercises"


def practices_dir(course: str, curriculum_root: Path | str | None = None) -> Path:
    """Return the practice-problems folder path (``curriculum/<course>/practices/``)."""
    return course_dir(course, curriculum_root) / "practices"


def exercise_path(
    course: str,
    exercise_number: str,
    curriculum_root: Path | str | None = None,
) -> Path:
    """Return the path to a course's exercise file (existence not guaranteed).

    The number is normalized to its non-padded form, so callers may pass either
    ``"1"`` or ``"01"`` and both resolve to ``exercise_1.txt``.
    """
    return exercises_dir(course, curriculum_root) / f"exercise_{_norm_num(exercise_number)}.txt"


def exercise_exists(
    course: str,
    exercise_number: str,
    curriculum_root: Path | str | None = None,
) -> bool:
    """True when the exercise file exists on disk."""
    if not course or not exercise_number:
        return False
    return exercise_path(course, exercise_number, curriculum_root).is_file()


def read_exercise(
    course: str,
    exercise_number: str,
    curriculum_root: Path | str | None = None,
) -> str:
    """Read an exercise file's text, or ``""`` when absent."""
    path = exercise_path(course, exercise_number, curriculum_root)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def practice_path(
    course: str,
    practice_number: str,
    curriculum_root: Path | str | None = None,
) -> Path:
    """Return the path to a course's practice-problem file (existence not guaranteed).

    The number is normalized to its non-padded form (``"07"`` and ``"7"`` both
    resolve to ``practice_7.txt``).
    """
    return practices_dir(course, curriculum_root) / f"practice_{_norm_num(practice_number)}.txt"


def practice_exists(
    course: str,
    practice_number: str,
    curriculum_root: Path | str | None = None,
) -> bool:
    """True when the practice-problem file exists on disk."""
    if not course or not practice_number:
        return False
    return practice_path(course, practice_number, curriculum_root).is_file()


def read_practice(
    course: str,
    practice_number: str,
    curriculum_root: Path | str | None = None,
) -> str:
    """Read a practice-problem file's text, or ``""`` when absent."""
    path = practice_path(course, practice_number, curriculum_root)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


# Optional per-course tutor-behavior delta appended to the base tutor prompt.
# A course drops ``curriculum/<course>/tutor_rules.txt`` holding ONLY its
# course-specific rules; the base prompt (tutor_07) stays the shared source of
# truth. See docs/superpowers/specs/2026-07-16-per-course-tutor-rules-design.md.
TUTOR_RULES_HEADER = "## Course-specific rules:"


def tutor_rules_path(course: str, curriculum_root: Path | str | None = None) -> Path:
    """Return the per-course tutor-rules file (``curriculum/<course>/tutor_rules.txt``)."""
    return course_dir(course, curriculum_root) / "tutor_rules.txt"


def read_course_tutor_rules(course: str, curriculum_root: Path | str | None = None) -> str:
    """Return the course's ``tutor_rules.txt`` stripped, or ``""`` if absent/empty."""
    if not course:
        return ""
    path = tutor_rules_path(course, curriculum_root)
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def append_course_tutor_rules(
    base_prompt: str, course: str, curriculum_root: Path | str | None = None
) -> str:
    """Append the course's tutor rules (under ``TUTOR_RULES_HEADER``) to *base_prompt*.

    Returns *base_prompt* unchanged when the course has no non-empty
    ``tutor_rules.txt``. The delta lands at the very end of the prompt, after any
    ``<Assignment>`` substitution has already run, so no base-prompt parsing is
    needed and the course rules get recency weight.
    """
    rules = read_course_tutor_rules(course, curriculum_root)
    if not rules:
        return base_prompt
    return f"{base_prompt}\n\n{TUTOR_RULES_HEADER}\n{rules}"


def pinned_dir(course: str, curriculum_root: Path | str | None = None) -> Path:
    """Return the always-pinned reference-context folder (``curriculum/<course>/pinned/``).

    Every ``*.txt`` here is folded directly into the tutor's context in
    ``full_context`` and ``rag`` modes (the course description, syllabus, and any
    other always-on material), and is deliberately NOT ingested by ``rag.sources``
    — so a pinned doc is never also retrieved. Use it for course reference material
    the tutor should always have on hand (e.g. a debugging flow chart), as opposed
    to per-exercise attachments.
    """
    return course_dir(course, curriculum_root) / "pinned"


def read_course_description(course: str, curriculum_root: Path | str | None = None) -> str:
    """Read the course description (``curriculum/<course>/pinned/course.txt``), or ``""``.

    A single-doc accessor for the short course-description text (used e.g. as the
    lean judge-context in the bulk-simulation runners), centralizing the pinned/
    location so callers don't hardcode the path.
    """
    if not course:
        return ""
    path = pinned_dir(course, curriculum_root) / "course.txt"
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def read_pinned_context(course: str, curriculum_root: Path | str | None = None) -> str:
    """Return the course's pinned reference docs joined into one block, or ``""``.

    Reads every ``pinned/*.txt`` (sorted by filename, each stripped) and joins them
    with blank lines; each file is expected to carry its own title as its first
    line. Empty/whitespace-only files are skipped; an absent folder yields ``""``.
    """
    if not course:
        return ""
    folder = pinned_dir(course, curriculum_root)
    if not folder.is_dir():
        return ""
    blocks: list[str] = []
    for path in sorted(folder.glob("*.txt")):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            blocks.append(text)
    return "\n\n".join(blocks)


# Label for the tutor-only correct-answer block that is paired directly with the
# current problem (never retrieved via RAG, never shown to the student).
SOLUTION_CONTEXT_LABEL = (
    "Correct answer & worked solution (FOR YOUR REFERENCE ONLY — use it to guide the "
    "student and check their work; never reveal it, or any part of it, directly):\n"
)


def exercises_solutions_dir(course: str, curriculum_root: Path | str | None = None) -> Path:
    """Return the exercise-solutions folder (``curriculum/<course>/exercises_solutions/``)."""
    return course_dir(course, curriculum_root) / "exercises_solutions"


def practices_solutions_dir(course: str, curriculum_root: Path | str | None = None) -> Path:
    """Return the practice-solutions folder (``curriculum/<course>/practices_solutions/``)."""
    return course_dir(course, curriculum_root) / "practices_solutions"


def solution_path(
    course: str,
    number: str,
    kind: str = "exercise",
    curriculum_root: Path | str | None = None,
) -> Path:
    """Return the path to a problem's solution file (existence not guaranteed).

    ``kind`` is ``"exercise"`` (``exercises_solutions/exercise_solution_<N>.txt``)
    or ``"practice"`` (``practices_solutions/practice_solution_<N>.txt``); the
    number is normalized to its non-padded form. The ``_solution_`` infix keeps
    solution filenames distinct from the problem files they mirror.
    """
    n = _norm_num(number)
    if kind == "practice":
        return practices_solutions_dir(course, curriculum_root) / f"practice_solution_{n}.txt"
    return exercises_solutions_dir(course, curriculum_root) / f"exercise_solution_{n}.txt"


def read_solution(
    course: str,
    number: str,
    kind: str = "exercise",
    curriculum_root: Path | str | None = None,
) -> str:
    """Read a problem's solution file text, or ``""`` when absent (many have none yet)."""
    if not course or not number:
        return ""
    path = solution_path(course, number, kind, curriculum_root)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def discover_practice(
    course: str,
    curriculum_root: Path | str | None = None,
) -> list[str]:
    """Return non-padded practice-problem numbers for a course, sorted numerically (e.g. ``['1', '2', '10']``)."""
    folder = practices_dir(course, curriculum_root)
    if not folder.is_dir():
        return []
    nums: set[str] = set()
    for path in folder.glob("practice_*.txt"):
        m = _PRACTICE_NAME_RE.match(path.name)
        if m:
            nums.add(str(int(m.group(1))))
    return sorted(nums, key=int)


def discover_exercises(
    course: str,
    curriculum_root: Path | str | None = None,
) -> list[str]:
    """Return non-padded exercise numbers for a course, sorted numerically (e.g. ``['1', '2', '10']``)."""
    folder = exercises_dir(course, curriculum_root)
    if not folder.is_dir():
        return []
    nums: set[str] = set()
    for path in folder.glob("exercise_*.txt"):
        m = _EXERCISE_NAME_RE.match(path.name)
        if m:
            nums.add(str(int(m.group(1))))
    return sorted(nums, key=int)


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


def course_name_path(course: str, curriculum_root: Path | str | None = None) -> Path:
    """Return the path to a course's display-name file (``curriculum/<course>/course_name.txt``)."""
    return course_dir(course, curriculum_root) / "course_name.txt"


def load_course_name(course: str | None, curriculum_root: Path | str | None = None) -> str:
    """Human-readable course name from ``curriculum/<course>/course_name.txt``.

    Returns ``""`` when the course is falsy or the file is missing/empty, so
    callers (banners, sidebar eyebrows) degrade gracefully until each
    ``course_name.txt`` is filled in. The curriculum file is the single source
    of truth for course display names.
    """
    if not course:
        return ""
    path = course_name_path(course, curriculum_root)
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def about_asktim_path(curriculum_root: Path | str | None = None) -> Path:
    """Return the path to the shared AskTIM self-description (``curriculum/about_asktim.txt``)."""
    return _root(curriculum_root) / "about_asktim.txt"


def load_about_asktim(curriculum_root: Path | str | None = None) -> str:
    """Read the AskTIM deployment blurb, stripped, or ``""`` when absent.

    Describes the AskTIM deployment so the tutor can coherently answer
    "what are you?" / "where am I?" questions. Shared by main_ui and sandbox_ui
    and prepended to the tutor context; it lives beside the course content
    rather than inside any single app so both read one source of truth.
    """
    path = about_asktim_path(curriculum_root)
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""
