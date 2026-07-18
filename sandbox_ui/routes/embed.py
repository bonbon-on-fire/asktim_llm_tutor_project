"""GET /embed — main iframe entry point.

All of `course`, `exercise`, and `tutor` are optional query params — any that
are absent fall back to the module defaults, so partial URLs still load. Values
that *are* supplied are validated against the on-disk curriculum and tutor
folders (via shared validators in `_validation`); an invalid explicit value
404s. Then renders the `embed.html` chat page.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from sandbox_ui.cookies import read_username_cookie
from sandbox_ui.routes._validation import (
    DEFAULT_COURSE,
    DEFAULT_EXERCISE,
    DEFAULT_TUTOR,
    list_context_options,
    load_course_name,
    resolve_embed_selection,
    validate_course,
    validate_exercise,
    validate_tutor,
)


embed_bp = Blueprint("embed", __name__)


def _bad_param(err: dict):
    """Build a 404 JSON response for an invalid course/exercise/tutor param."""
    return jsonify({"error": "invalid_param", **err}), 404


def _render_embed(*, course: str, exercise: str, tutor: str, exercise_kind: str = "exercise"):
    """Render the embed.html chat widget for the given course/exercise|practice/tutor context."""
    tutor_config = {
        "course": course,
        "exercise": exercise,
        "tutor": tutor,
        "exerciseKind": exercise_kind,
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


@embed_bp.get("/api/context/options")
def context_options():
    """Courses (+ their exercises and lecture/RAG availability) and tutor prompts,
    used to populate the sandbox_ui Change-context switcher."""
    return jsonify(list_context_options())


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
    """Render the chat widget from query params (exercise XOR practice), validating the resolved value."""
    course = request.args.get("course") or DEFAULT_COURSE
    tutor = DEFAULT_TUTOR  # sandbox is locked to a single tutor prompt

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
