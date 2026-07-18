"""GET /embed — main iframe entry point.

`course`, `exercise`, and `tutor` are optional query params — any absent one
falls back to the module defaults, so partial URLs still load. A `practice=<n>`
param selects a practice problem instead of an exercise; supplying both
`exercise` and `practice` is rejected (404). Supplied values are validated
against the on-disk curriculum and tutor folders (via shared validators in
`_validation`); an invalid explicit value 404s. Then renders the `embed.html`
chat page.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from main_ui.cookies import read_username_cookie
from main_ui.routes._validation import (
    DEFAULT_COURSE,
    DEFAULT_EXERCISE,
    DEFAULT_TUTOR,
    load_course_name,
    resolve_embed_selection,
    validate_course,
    validate_tutor,
)


embed_bp = Blueprint("embed", __name__)


def _bad_param(err: dict):
    """Build a 404 JSON response for a validation-failure dict."""
    return jsonify({"error": "invalid_param", **err}), 404


def _render_embed(*, course: str, exercise: str, tutor: str, exercise_kind: str = "exercise"):
    """Render ``embed.html`` for the given course/exercise|practice/tutor context."""
    tutor_config = {
        "course": course,
        "exercise": exercise,
        "tutor": tutor,
        "exercise_kind": exercise_kind,
    }
    has_email = bool(read_username_cookie(request))
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
    """Resolve course + exercise|practice from query params, validate, and render.

    `exercise` and `practice` are mutually exclusive; supplying both 404s. A
    missing number falls back to the default exercise; an explicitly invalid
    value 404s.
    """
    course = request.args.get("course") or DEFAULT_COURSE
    tutor = DEFAULT_TUTOR  # production is locked to a single tutor prompt

    err = validate_course(course)
    if err:
        return _bad_param(err)

    number, kind, err = resolve_embed_selection(
        course, request.args.get("exercise"), request.args.get("practice"), DEFAULT_EXERCISE
    )
    if err:
        return _bad_param(err)

    err = validate_tutor(tutor)
    if err:
        return _bad_param(err)

    return _render_embed(course=course, exercise=number, tutor=tutor, exercise_kind=kind)
