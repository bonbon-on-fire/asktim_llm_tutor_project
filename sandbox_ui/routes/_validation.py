"""Shared validators for `course`, `exercise`, and `tutor` request params.

Used by both `routes/embed.py` (Step 3) and `routes/chat.py` (Step 5). Each
validator returns ``None`` on success or a dict describing the failure
(``{param, value, reason}``) so routes can map it to their preferred HTTP
response shape.
"""

from __future__ import annotations

from pathlib import Path

from utils.curriculum import discover_exercises as _discover_exercises
from utils.curriculum import exercise_exists as _exercise_exists
from utils.curriculum import read_exercise as _read_exercise
from utils.curriculum import discover_practice as _discover_practice
from utils.curriculum import practice_exists as _practice_exists
from utils.curriculum import read_practice as _read_practice


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_TUTOR_PROMPTS_DIR = _REPO_ROOT / "tutor" / "prompts"

DEFAULT_TUTOR = "tutor_05"
DEFAULT_COURSE = "cities_and_climate_change"
DEFAULT_EXERCISE = "01"


def _list_courses() -> set[str]:
    if not _CURRICULUM_DIR.is_dir():
        return set()
    return {p.name for p in _CURRICULUM_DIR.iterdir() if p.is_dir()}


def _tutor_prompt_exists(tutor: str) -> bool:
    return (_TUTOR_PROMPTS_DIR / f"{tutor}.txt").is_file()


def _err(param: str, value, reason: str) -> dict:
    return {"param": param, "value": value, "reason": reason}


def validate_course(course) -> dict | None:
    if not course:
        return _err("course", course, "missing")
    if course not in _list_courses():
        return _err("course", course, "no such course")
    return None


def validate_exercise(course, exercise) -> dict | None:
    if not exercise:
        return _err("exercise", exercise, "missing")
    if not (isinstance(exercise, str) and len(exercise) == 2 and exercise.isdigit()):
        return _err(
            "exercise", exercise, "must be a zero-padded 2-digit number (e.g. 04)"
        )
    if not _exercise_exists(course, exercise):
        return _err(
            "exercise", exercise, f"no exercise_{exercise}.txt under curriculum/{course}/exercises/"
        )
    return None


def validate_practice(course, practice) -> dict | None:
    if not practice:
        return _err("practice", practice, "missing")
    if not (isinstance(practice, str) and len(practice) == 2 and practice.isdigit()):
        return _err(
            "practice", practice, "must be a zero-padded 2-digit number (e.g. 04)"
        )
    if not _practice_exists(course, practice):
        return _err(
            "practice", practice,
            f"no practice_{practice}.txt under curriculum/{course}/practices/",
        )
    return None


def validate_tutor(tutor) -> dict | None:
    if not tutor:
        return _err("tutor", tutor, "missing")
    if not _tutor_prompt_exists(tutor):
        return _err("tutor", tutor, "no such tutor prompt")
    return None


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


def load_course_text(course) -> str:
    """Raw course.txt for a built-in course (preview for the Create wizard)."""
    if not course:
        return ""
    path = _CURRICULUM_DIR / course / "course.txt"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def load_exercise_text(course, exercise) -> str:
    """Raw exercise_<NN>.txt for a built-in course/exercise."""
    if not course or not exercise:
        return ""
    return _read_exercise(course, exercise)


def load_practice_text(course, practice) -> str:
    """Raw practice_<NN>.txt for a built-in course/practice problem."""
    if not course or not practice:
        return ""
    return _read_practice(course, practice)


def load_tutor_text(tutor) -> str:
    """Raw tutor prompt text for a built-in tutor stem."""
    if not tutor:
        return ""
    path = _TUTOR_PROMPTS_DIR / f"{tutor}.txt"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def load_syllabus_text(course) -> str:
    """Raw syllabus.txt for a built-in course (empty string if none)."""
    if not course:
        return ""
    path = _CURRICULUM_DIR / course / "syllabus.txt"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def list_exercises(course) -> list[str]:
    """Sorted zero-padded 2-digit exercise numbers available for a course."""
    if not course:
        return []
    return _discover_exercises(course)


def list_practice(course) -> list[str]:
    """Sorted zero-padded 2-digit practice-problem numbers for a course."""
    if not course:
        return []
    return _discover_practice(course)


def course_has_syllabus(course) -> bool:
    """True if the course ships a syllabus.txt that can be toggled into context."""
    if not course:
        return False
    return (_CURRICULUM_DIR / course / "syllabus.txt").is_file()


def course_has_rag(course) -> bool:
    """True if the course has a built RAG index (enables the wizard's RAG toggle)."""
    if not course:
        return False
    from rag.retrieve import has_index as _rag_has_index  # lazy: avoid import cost at boot

    return _rag_has_index(course)


def list_tutors() -> list[str]:
    """Sorted tutor prompt stems available under tutor/prompts/."""
    if not _TUTOR_PROMPTS_DIR.is_dir():
        return []
    return sorted(p.stem for p in _TUTOR_PROMPTS_DIR.glob("*.txt"))


def list_context_options() -> dict:
    """Full option set for the sandbox_ui Change-context switcher.

    Shape:
        {
          "courses": [
            {"slug": ..., "name": ..., "exercises": [...], "practice": [...], "has_syllabus": bool, "has_rag": bool},
            ...
          ],
          "tutors": ["tutor_01", ...],
        }
    """
    courses = []
    for slug in sorted(_list_courses()):
        courses.append(
            {
                "slug": slug,
                "name": load_course_name(slug),
                "exercises": list_exercises(slug),
                "practice": list_practice(slug),
                "has_syllabus": course_has_syllabus(slug),
                "has_rag": course_has_rag(slug),
            }
        )
    return {"courses": courses, "tutors": list_tutors()}


def validate_selection(course, number, kind) -> dict | None:
    """Validate a (kind, number) assignment selection against the right prefix."""
    if kind == "practice":
        return validate_practice(course, number)
    return validate_exercise(course, number)
