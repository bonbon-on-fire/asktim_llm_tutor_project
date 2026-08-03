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
from utils.curriculum import discover_practice as _discover_practice
from utils.curriculum import practice_exists as _practice_exists
from utils.curriculum import load_course_name as _load_course_name
from utils.curriculum import list_courses as _list_active_courses
from utils.curriculum import read_exercise as _read_exercise
from utils.curriculum import read_practice as _read_practice


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_TUTOR_PROMPTS_DIR = _REPO_ROOT / "tutor" / "prompts"

DEFAULT_TUTOR = "tutor_07"
DEFAULT_COURSE = "supply_chain_design"
DEFAULT_EXERCISE = "01"


def _list_courses() -> set[str]:
    """Slugs of all ACTIVE built-in courses (subdirectories of curriculum/).

    Delegates to utils.curriculum so archived courses (under
    ``curriculum/_archive/``) are excluded in exactly one place.
    """
    return set(_list_active_courses(_CURRICULUM_DIR))


def _tutor_prompt_exists(tutor: str) -> bool:
    """True if tutor/prompts/<tutor>.txt exists."""
    return (_TUTOR_PROMPTS_DIR / f"{tutor}.txt").is_file()


def _err(param: str, value, reason: str) -> dict:
    """Build a validation-failure dict of the form {param, value, reason}."""
    return {"param": param, "value": value, "reason": reason}


def validate_course(course) -> dict | None:
    """Return a failure dict if course is missing or unknown, else None."""
    if not course:
        return _err("course", course, "missing")
    if course not in _list_courses():
        return _err("course", course, "no such course")
    return None


def validate_exercise(course, exercise) -> dict | None:
    """Return a failure dict if exercise is missing, non-numeric, or absent for the course, else None."""
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
    """Return a failure dict if practice is missing, non-numeric, or absent for the course, else None."""
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


def validate_tutor(tutor) -> dict | None:
    """Return a failure dict if tutor is missing or has no prompt file, else None."""
    if not tutor:
        return _err("tutor", tutor, "missing")
    if not _tutor_prompt_exists(tutor):
        return _err("tutor", tutor, "no such tutor prompt")
    return None


def load_course_name(course) -> str:
    """Display name for a course, read from curriculum/<course>/course_name.txt.

    Thin wrapper over :func:`utils.curriculum.load_course_name` (the single
    source of truth) so existing call sites keep their import path.
    """
    return _load_course_name(course)


def list_exercises(course) -> list[str]:
    """Non-padded exercise numbers available for a course, sorted numerically."""
    if not course:
        return []
    return _discover_exercises(course)


def list_practice(course) -> list[str]:
    """Non-padded practice-problem numbers for a course, sorted numerically."""
    if not course:
        return []
    return _discover_practice(course)


def course_has_lectures(course) -> bool:
    """True if the course ships any lectures/*.txt that can be toggled into context."""
    if not course:
        return False
    lectures_dir = _CURRICULUM_DIR / course / "lectures"
    return lectures_dir.is_dir() and any(lectures_dir.glob("*.txt"))


def course_has_rag(course) -> bool:
    """True if the course has a built RAG index (enables the wizard's RAG toggle)."""
    if not course:
        return False
    from rag.retrieve import has_index as _rag_has_index  # lazy: avoid import cost at boot

    return _rag_has_index(course)


def list_tutors() -> list[str]:
    """Sorted tutor prompt stems available under tutor/prompts/.

    The wizard lists every built-in for visibility, but the Tutor prompt step is
    locked to `tutor_07` (disabled dropdown) and the routes ignore any
    client-supplied tutor, so the full list is display-only.
    """
    if not _TUTOR_PROMPTS_DIR.is_dir():
        return []
    return sorted(p.stem for p in _TUTOR_PROMPTS_DIR.glob("*.txt"))


def list_context_options() -> dict:
    """Full option set for the sandbox_ui Change-context switcher.

    Shape:
        {
          "courses": [
            {"slug": ..., "name": ..., "exercises": [...], "practice": [...], "has_lectures": bool, "has_rag": bool},
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
                "has_lectures": course_has_lectures(slug),
                "has_rag": course_has_rag(slug),
            }
        )
    return {"courses": courses, "tutors": list_tutors()}


def validate_selection(course, number, kind) -> dict | None:
    """Validate a (kind, number) assignment selection against the right prefix."""
    if kind == "practice":
        return validate_practice(course, number)
    return validate_exercise(course, number)


def _split_title(raw: str) -> tuple[str, str]:
    """Split an assignment file into (title, body).

    Assignment files start with a ``TITLE: ...`` line; that line becomes the
    title and the rest becomes the body. Files without one return ``("", text)``.
    """
    text = (raw or "").strip("\n")
    if not text:
        return "", ""
    lines = text.split("\n")
    first = lines[0].strip()
    if first.upper().startswith("TITLE:"):
        return first.split(":", 1)[1].strip(), "\n".join(lines[1:]).strip("\n")
    return "", text


def load_selection_preview(course, number, kind) -> dict:
    """Return ``{title, text}`` for an exercise/practice, both ``""`` when absent.

    Used by the Create-context wizard's exercise-preview step; callers validate
    the selection first (see :func:`validate_selection`).
    """
    raw = _read_practice(course, number) if kind == "practice" else _read_exercise(course, number)
    title, body = _split_title(raw)
    return {"title": title, "text": body}


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
