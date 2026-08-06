"""GET /embed — main iframe entry point.

There is no default course: with no `course` query param there's nothing to
load, so the page renders with an empty course context. It still loads
normally, but the first chat send fails course validation and surfaces the
error banner (see `routes/chat.py`) — better than silently falling back to a
default course that may have been archived. This matches main_ui. `exercise`
still falls back to the module default when a course IS given. A `practice=<n>`
param selects a practice problem instead of an exercise; supplying both
`exercise` and `practice` is rejected (404). Supplied values are validated
against the on-disk curriculum and tutor folders (via shared validators in
`_validation`); an invalid explicit value 404s. Then renders the `embed.html`
chat page.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from sandbox_ui.cookies import read_username_cookie
from sandbox_ui.routes._validation import (
    DEFAULT_EXERCISE,
    DEFAULT_TUTOR,
    list_context_options,
    load_course_name,
    load_selection_preview,
    resolve_embed_selection,
    validate_course,
    validate_selection,
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


@embed_bp.get("/api/context/exercise")
def context_exercise():
    """Title + full prompt text for one exercise/practice (the wizard's preview).

    Params: ``course``, ``number``, and ``kind`` (``exercise`` default, or
    ``practice``). The selection is validated the same way the embed route
    validates it, so an unknown course/number 404s.
    """
    course = request.args.get("course") or ""
    number = request.args.get("number") or ""
    kind = "practice" if request.args.get("kind") == "practice" else "exercise"

    err = validate_course(course)
    if err:
        return _bad_param(err)
    err = validate_selection(course, number, kind)
    if err:
        return _bad_param(err)

    preview = load_selection_preview(course, number, kind)
    return jsonify({"course": course, "number": number, "kind": kind, **preview})


@embed_bp.get("/")
def index():
    """Default entry point for bare host URLs (e.g. Railway public domain).

    No default course: render an empty course context so the page loads but the
    first chat send surfaces the error (see module docstring). Matches main_ui.
    """
    return _render_embed(course="", exercise="", tutor=DEFAULT_TUTOR)


@embed_bp.get("/embed")
def embed():
    """Render the chat widget from query params (exercise XOR practice), validating the resolved value.

    A missing `course` has no default: render an empty course context so the
    page loads and the first send surfaces the error, rather than falling back
    to a default course. Matches main_ui.
    """
    tutor = DEFAULT_TUTOR  # sandbox is locked to a single tutor prompt

    course = request.args.get("course")
    if not course:
        return _render_embed(course="", exercise="", tutor=tutor)

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
