"""GET /embed — main iframe entry point.

All of `course`, `exercise`, and `tutor` are optional query params — any that
are absent fall back to the module defaults, so partial URLs still load. Values
that *are* supplied are validated against the on-disk curriculum and tutor
folders (via shared validators in `_validation`); an invalid explicit value
404s. Then renders the `embed.html` chat page.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from main_ui.cookies import USERNAME_COOKIE_NAME
from main_ui.routes._validation import (
    DEFAULT_COURSE,
    DEFAULT_EXERCISE,
    DEFAULT_TUTOR,
    load_course_name,
    validate_course,
    validate_exercise,
    validate_tutor,
)


embed_bp = Blueprint("embed", __name__)


def _bad_param(err: dict):
    """Build a 404 JSON response for a validation-failure dict."""
    return jsonify({"error": "invalid_param", **err}), 404


def _render_embed(*, course: str, exercise: str, tutor: str):
    """Render ``embed.html`` for the given course/exercise/tutor context."""
    tutor_config = {"course": course, "exercise": exercise, "tutor": tutor}
    has_email = bool(request.cookies.get(USERNAME_COOKIE_NAME))
    return render_template(
        "embed.html",
        course=course,
        exercise=exercise,
        tutor=tutor,
        course_name=load_course_name(course),
        tutor_config=tutor_config,
        has_email=has_email,
    )


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
    """Resolve course/exercise/tutor from query params (with defaults), validate, and render.

    Any absent param falls back to the module default so partial URLs still
    load; an explicitly invalid value 404s.
    """
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
