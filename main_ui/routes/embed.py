"""GET /embed — main iframe entry point.

There is no default course: with no `course` query param there's nothing to
load, so the page renders with an empty course context. It still loads
normally, but the first chat send fails course validation and surfaces the
error banner (see `routes/chat.py`) — better than silently falling back to a
default course that may have been archived. `exercise` still falls back to the
module default when a course IS given. A `practice=<n>` param selects a
practice problem instead of an exercise; supplying both `exercise` and
`practice` is rejected (404). Supplied values are validated against the on-disk
curriculum and tutor folders (via shared validators in `_validation`); an
invalid explicit value 404s. Then renders the `embed.html` chat page.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from utils.curriculum import load_ui_labels

from main_ui.cookies import read_username_cookie
from main_ui.routes._validation import (
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
        # Per-course sidebar/history labels by exercise_kind (e.g. this course
        # renders practices as "Week N Practice Problems"); chat.js formats the
        # entry header from this. Defaults to "Exercise N"/"Practice N".
        "labels": load_ui_labels(course),
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
    """Default entry point for bare host URLs (e.g. Railway public domain).

    No default course: render an empty course context so the page loads but the
    first chat send surfaces the error (see module docstring).
    """
    return _render_embed(course="", exercise="", tutor=DEFAULT_TUTOR)


@embed_bp.get("/embed")
def embed():
    """Resolve course + exercise|practice from query params, validate, and render.

    A missing `course` has no default: render an empty course context so the
    page loads and the first send surfaces the error, rather than falling back
    to a default course. `exercise` and `practice` are mutually exclusive;
    supplying both 404s. A missing number falls back to the default exercise; an
    explicitly invalid value 404s.
    """
    tutor = DEFAULT_TUTOR  # production is locked to a single tutor prompt

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
