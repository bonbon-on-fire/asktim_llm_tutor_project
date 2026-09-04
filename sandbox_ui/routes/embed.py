"""GET /embed — main iframe entry point.

There is no default course: with no `course` query param there's nothing to
load, so the page renders with an empty course context. It still loads
normally, but the first chat send fails course validation and surfaces the
error banner (see `routes/chat.py`) — better than silently falling back to a
default course that may have been archived. This matches main_ui. `exercise`
still falls back to the module default when a course IS given. A `practice=<n>`
param selects a practice problem, and a `case=<n>` param selects a case study,
instead of an exercise; supplying more than one of `exercise`/`practice`/`case`
is rejected (404). An optional `problem=<n>` param
marks a single sub-problem as the student's focus; an invalid value
(non-integer or out-of-range) 404s. Supplied values are validated against the
on-disk curriculum and tutor folders (via shared validators in `_validation`);
an invalid explicit value 404s. Then renders the `embed.html` chat page.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from sandbox_ui.cookies import read_username_cookie
from sandbox_ui.routes._validation import (
    DEFAULT_EXERCISE,
    DEFAULT_ROLE,
    list_context_options,
    load_course_name,
    load_selection_preview,
    resolve_embed_selection,
    role_default_prompt,
    validate_course,
    validate_problem,
    validate_role,
    validate_selection,
    validate_tutor,
)


embed_bp = Blueprint("embed", __name__)


def _bad_param(err: dict):
    """Build a 404 JSON response for an invalid course/exercise/tutor param."""
    return jsonify({"error": "invalid_param", **err}), 404


def _render_embed(*, course: str, exercise: str, tutor: str, exercise_kind: str = "exercise", role: str = DEFAULT_ROLE, problem: str | None = None):
    """Render the embed.html chat widget for the given course/exercise|practice/tutor/role/problem context."""
    tutor_config = {
        "course": course,
        "exercise": exercise,
        "tutor": tutor,
        "role": role,
        "exerciseKind": exercise_kind,
    }
    if problem:
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


@embed_bp.get("/api/context/options")
def context_options():
    """Courses (+ their exercises and lecture/RAG availability) and tutor prompts,
    used to populate the sandbox_ui Change-context switcher."""
    return jsonify(list_context_options())


@embed_bp.get("/api/context/exercise")
def context_exercise():
    """Title + full prompt text for one exercise/practice (the wizard's preview).

    Params: ``course``, ``number``, and ``kind`` (``exercise`` default, or
    ``practice``/``case``). The selection is validated the same way the embed
    route validates it, so an unknown course/number 404s.
    """
    course = request.args.get("course") or ""
    number = request.args.get("number") or ""
    _kind = request.args.get("kind")
    kind = _kind if _kind in ("practice", "case") else "exercise"

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

    No default course: render an empty course context (page loads, first send
    404s). Role defaults to tutor. Matches main_ui.
    """
    return _render_embed(
        course="", exercise="", tutor=role_default_prompt(DEFAULT_ROLE), role=DEFAULT_ROLE
    )


@embed_bp.get("/embed")
def embed():
    """Render the chat widget from query params (exercise XOR practice), validating the resolved value."""
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
        course,
        request.args.get("exercise"),
        request.args.get("practice"),
        request.args.get("case"),
        DEFAULT_EXERCISE,
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
