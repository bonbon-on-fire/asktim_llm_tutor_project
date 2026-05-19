"""Shared validators for `course`, `exercise`, and `tutor` request params.

Used by both `routes/embed.py` (Step 3) and `routes/chat.py` (Step 5). Each
validator returns ``None`` on success or a dict describing the failure
(``{param, value, reason}``) so routes can map it to their preferred HTTP
response shape.
"""

from __future__ import annotations

from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_TUTOR_PROMPTS_DIR = _REPO_ROOT / "tutor" / "prompts"

DEFAULT_TUTOR = "tutor_05"


def _list_courses() -> set[str]:
    if not _CURRICULUM_DIR.is_dir():
        return set()
    return {p.name for p in _CURRICULUM_DIR.iterdir() if p.is_dir()}


def _exercise_exists(course: str, exercise_number: str) -> bool:
    return (_CURRICULUM_DIR / course / f"exercise_{exercise_number}.txt").is_file()


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
            "exercise", exercise, f"no exercise_{exercise}.txt under curriculum/{course}/"
        )
    return None


def validate_tutor(tutor) -> dict | None:
    if not tutor:
        return _err("tutor", tutor, "missing")
    if not _tutor_prompt_exists(tutor):
        return _err("tutor", tutor, "no such tutor prompt")
    return None
