"""GET /embed — main iframe entry point.

There is no default course: with no `course` query param there's nothing to
load, so the page renders with an empty course context. It still loads
normally, but the first chat send fails course validation and surfaces the
error banner (see `routes/chat.py`) — better than silently falling back to a
default course that may have been archived. `exercise` still falls back to the
module default when a course IS given. A `practice=<n>` param selects a
practice problem instead of an exercise; supplying both `exercise` and
`practice` is rejected (404). An optional `problem=<n>` param marks a single
sub-problem as the student's focus; an invalid value (non-integer or out-of-range)
404s. Supplied values are validated against the on-disk curriculum and tutor
folders (via shared validators in `_validation`); an invalid explicit value 404s.
Then renders the `embed.html` chat page.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from utils.curriculum import load_ui_labels

from main_ui.cookies import read_username_cookie
from main_ui.routes._validation import (
    DEFAULT_EXERCISE,
    DEFAULT_ROLE,
    DEFAULT_TUTOR,
    load_course_name,
    resolve_embed_selection,
    role_default_prompt,
    validate_course,
    validate_problem,
    validate_role,
    validate_tutor,
)


embed_bp = Blueprint("embed", __name__)


def _bad_param(err: dict):
    """Build a 404 JSON response for a validation-failure dict."""
    return jsonify({"error": "invalid_param", **err}), 404


def _render_embed(*, course: str, exercise: str, tutor: str, exercise_kind: str = "exercise", role: str = DEFAULT_ROLE, problem: str | None = None):
    """Render ``embed.html`` for the given course/exercise|practice/tutor/role/problem context."""
    tutor_config = {
        "course": course,
        "exercise": exercise,
        "tutor": tutor,
        "role": role,
        "exercise_kind": exercise_kind,
        # Per-course sidebar/history labels by exercise_kind (e.g. this course
        # renders practices as "Week N Practice Problems"); chat.js formats the
        # entry header from this. Defaults to "Exercise N"/"Practice N".
        "labels": load_ui_labels(course),
    }
    if problem:
        # Focus sub-problem (optional). Omitted when absent so no-focus config
        # stays byte-identical to today. Stored as an int for the frontend echo.
        tutor_config["problem"] = int(problem)
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
    first chat send surfaces the error (see module docstring). Role defaults to
    tutor.
    """
    return _render_embed(
        course="", exercise="", tutor=role_default_prompt(DEFAULT_ROLE), role=DEFAULT_ROLE
    )


@embed_bp.get("/embed")
def embed():
    """Resolve role + course + exercise|practice from query params, validate, and render."""
    role = request.args.get("role") or DEFAULT_ROLE
    err = validate_role(role)
    if err:
        return _bad_param(err)
    tutor = role_default_prompt(role)

    course = request.args.get("course")
    if not course:
        return _render_embed(course="", exercise="", tutor=tutor, role=role)

    err = validate_course(course)
    if err:
        return _bad_param(err)

    number, kind, err = resolve_embed_selection(
        course, request.args.get("exercise"), request.args.get("practice"), DEFAULT_EXERCISE
    )
    if err:
        return _bad_param(err)

    problem = request.args.get("problem")
    err = validate_problem(course, number, kind, problem)
    if err:
        return _bad_param(err)

    err = validate_tutor(tutor)
    if err:
        return _bad_param(err)

    return _render_embed(course=course, exercise=number, tutor=tutor, exercise_kind=kind, role=role, problem=problem)
