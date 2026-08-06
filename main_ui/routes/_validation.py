"""Shared validators for `course`, `exercise`, and `tutor` request params.

Used by both `routes/embed.py` (Step 3) and `routes/chat.py` (Step 5). Each
validator returns ``None`` on success or a dict describing the failure
(``{param, value, reason}``) so routes can map it to their preferred HTTP
response shape.
"""

from __future__ import annotations

from pathlib import Path

from tutor.roles import DEFAULT_ROLE, get_role
from utils.curriculum import discover_practice as _discover_practice
from utils.curriculum import exercise_exists as _exercise_exists
from utils.curriculum import practice_exists as _practice_exists
from utils.curriculum import list_courses as _list_active_courses
from utils.curriculum import subproblem_label


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_TUTOR_PROMPTS_DIR = _REPO_ROOT / "tutor" / "prompts"

DEFAULT_TUTOR = "tutor_07"
DEFAULT_COURSE = "cities_and_climate_change"
DEFAULT_EXERCISE = "01"


def _list_courses() -> set[str]:
    """Return the set of ACTIVE course directory names under ``curriculum/``.

    Delegates to utils.curriculum so archived courses (under
    ``curriculum/_archive/``) are excluded in exactly one place.
    """
    return set(_list_active_courses(_CURRICULUM_DIR))


def _tutor_prompt_exists(tutor: str) -> bool:
    """True if ``tutor/prompts/<tutor>.txt`` exists."""
    return (_TUTOR_PROMPTS_DIR / f"{tutor}.txt").is_file()


def _err(param: str, value, reason: str) -> dict:
    """Build a validation-failure dict of ``{param, value, reason}``."""
    return {"param": param, "value": value, "reason": reason}


def validate_course(course) -> dict | None:
    """Return None if *course* names an existing course, else a failure dict."""
    if not course:
        return _err("course", course, "missing")
    if course not in _list_courses():
        return _err("course", course, "no such course")
    return None


def validate_exercise(course, exercise) -> dict | None:
    """Return None if *exercise* is a digit string with a file under *course*, else a failure dict."""
    if not exercise:
        return _err("exercise", exercise, "missing")
    if not (isinstance(exercise, str) and exercise.isdigit()):
        return _err(
            "exercise", exercise, "must be a non-negative integer (e.g. 4)"
        )
    if not _exercise_exists(course, exercise):
        return _err(
            "exercise", exercise, f"no exercise_{exercise}.txt under curriculum/{course}/exercises/"
        )
    return None


def validate_practice(course, practice) -> dict | None:
    """Return None if *practice* is a digit string with a file under *course*, else a failure dict."""
    if not practice:
        return _err("practice", practice, "missing")
    if not (isinstance(practice, str) and practice.isdigit()):
        return _err(
            "practice", practice, "must be a non-negative integer (e.g. 4)"
        )
    if not _practice_exists(course, practice):
        return _err(
            "practice", practice,
            f"no practice_{practice}.txt under curriculum/{course}/practices/",
        )
    return None


def validate_selection(course, number, kind) -> dict | None:
    """Validate a (kind, number) selection against the matching content folder."""
    if kind == "practice":
        return validate_practice(course, number)
    return validate_exercise(course, number)


def validate_problem(course, number, kind, problem) -> dict | None:
    """None when problem is absent (no focus) or valid; else a failure dict.

    Empty/None problem is a no-op (focus is optional). Otherwise it must be a
    positive-integer string naming an existing sub-problem in the resolved file.
    """
    if not problem:
        return None
    if not (isinstance(problem, str) and problem.isdigit()):
        return _err("problem", problem, "must be a positive integer (e.g. 2)")
    if subproblem_label(course, number, kind, problem) is None:
        return _err("problem", problem, f"no sub-problem {problem} in {kind} {number} of {course}")
    return None


def resolve_embed_selection(course, raw_exercise, raw_practice, default_exercise):
    """Resolve (number, kind) from embed query params.

    Returns ``(number, kind, err)``. ``err`` is a failure dict (mapped to 404 by
    the route) when both params are supplied or the resolved value is invalid;
    ``number``/``kind`` are None on the both-params error.
    """
    if raw_exercise and raw_practice:
        return None, None, _err(
            "selection", "exercise+practice",
            "cannot specify both exercise and practice",
        )
    if raw_practice:
        return raw_practice, "practice", validate_practice(course, raw_practice)
    number = raw_exercise or default_exercise
    return number, "exercise", validate_exercise(course, number)


def list_practice(course) -> list[str]:
    """Non-padded practice-problem numbers for a course, sorted numerically."""
    if not course:
        return []
    return _discover_practice(course)


def validate_tutor(tutor) -> dict | None:
    """Return None if *tutor* names an existing tutor prompt, else a failure dict."""
    if not tutor:
        return _err("tutor", tutor, "missing")
    if not _tutor_prompt_exists(tutor):
        return _err("tutor", tutor, "no such tutor prompt")
    return None


def validate_role(role) -> dict | None:
    """Return None if *role* names a registered role, else a failure dict."""
    if not role:
        return _err("role", role, "missing")
    if get_role(role) is None:
        return _err("role", role, "no such role")
    return None


def role_default_prompt(role) -> str | None:
    """Return the default prompt name for *role* (e.g. 'tutor' -> 'tutor_07')."""
    r = get_role(role)
    return r.default_prompt if r else None


def load_course_name(course) -> str:
    """Display name for a course, read from curriculum/<course>/course_name.txt.

    Returns "" if the course is falsy or the file is missing/empty, so the
    banner degrades gracefully until each course_name.txt is filled in.
    """
    if not course:
        return ""
    path = _CURRICULUM_DIR / course / "course_name.txt"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8").strip()
