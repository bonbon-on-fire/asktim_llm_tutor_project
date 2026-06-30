"""GET /embed — main iframe entry point.

All of `course`, `exercise`, and `tutor` are optional query params — any that
are absent fall back to the module defaults, so partial URLs still load. Values
that *are* supplied are validated against the on-disk curriculum and tutor
folders (via shared validators in `_validation`); an invalid explicit value
404s. Then renders the `embed.html` chat page.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from sandbox_ui.cookies import EMAIL_COOKIE_NAME
from sandbox_ui.routes._validation import (
    DEFAULT_COURSE,
    DEFAULT_EXERCISE,
    DEFAULT_TUTOR,
    list_context_options,
    load_course_name,
    load_course_text,
    load_exercise_text,
    load_practice_text,
    load_syllabus_text,
    load_tutor_text,
    validate_course,
    validate_exercise,
    validate_practice,
    validate_tutor,
)


embed_bp = Blueprint("embed", __name__)


def _bad_param(err: dict):
    return jsonify({"error": "invalid_param", **err}), 404


def _render_embed(*, course: str, exercise: str, tutor: str, syllabus: bool = True):
    tutor_config = {
        "course": course,
        "exercise": exercise,
        "tutor": tutor,
        "syllabus": syllabus,
    }
    has_email = bool(request.cookies.get(EMAIL_COOKIE_NAME))
    return render_template(
        "embed.html",
        course=course,
        exercise=exercise,
        tutor=tutor,
        course_name=load_course_name(course),
        tutor_config=tutor_config,
        has_email=has_email,
    )


@embed_bp.get("/api/context/options")
def context_options():
    """Courses (+ their exercises and syllabus availability) and tutor prompts,
    used to populate the sandbox_ui Change-context switcher."""
    return jsonify(list_context_options())


@embed_bp.get("/api/context/preview")
def context_preview():
    """Raw text of a built-in course/exercise/tutor/syllabus, so the
    Create-context wizard can show it (read-only) when an existing option is
    selected. Inputs are validated first to prevent path traversal."""
    kind = request.args.get("kind")
    course = request.args.get("course")
    exercise = request.args.get("exercise")
    tutor = request.args.get("tutor")

    if kind == "course":
        err = validate_course(course)
        if err:
            return _bad_param(err)
        return jsonify({"text": load_course_text(course)})
    if kind == "exercise":
        err = validate_course(course) or validate_exercise(course, exercise)
        if err:
            return _bad_param(err)
        return jsonify({"text": load_exercise_text(course, exercise)})
    if kind == "practice":
        err = validate_course(course) or validate_practice(course, exercise)
        if err:
            return _bad_param(err)
        return jsonify({"text": load_practice_text(course, exercise)})
    if kind == "tutor":
        err = validate_tutor(tutor)
        if err:
            return _bad_param(err)
        return jsonify({"text": load_tutor_text(tutor)})
    if kind == "syllabus":
        err = validate_course(course)
        if err:
            return _bad_param(err)
        return jsonify({"text": load_syllabus_text(course)})
    return jsonify({"error": "bad_kind", "reason": "unknown preview kind"}), 400


@embed_bp.get("/")
def index():
    """Default entry point for bare host URLs (e.g. Railway public domain)."""
    return _render_embed(
        course=DEFAULT_COURSE,
        exercise=DEFAULT_EXERCISE,
        tutor=DEFAULT_TUTOR,
    )


@embed_bp.get("/embed")
def embed():
    # Missing params fall back to defaults so partial URLs (e.g. ?exercise=02)
    # still load instead of 404ing. An *explicitly* invalid value is still
    # rejected below, since validation runs on the resolved value either way.
    course = request.args.get("course") or DEFAULT_COURSE
    exercise = request.args.get("exercise") or DEFAULT_EXERCISE
    tutor = request.args.get("tutor") or DEFAULT_TUTOR

    err = validate_course(course)
    if err:
        return _bad_param(err)
    err = validate_exercise(course, exercise)
    if err:
        return _bad_param(err)
    err = validate_tutor(tutor)
    if err:
        return _bad_param(err)

    return _render_embed(course=course, exercise=exercise, tutor=tutor)
