"""GET /embed — main iframe entry point.

Validates `course`, `exercise`, and optional `tutor` query params against the
on-disk curriculum and tutor folders (via shared validators in `_validation`),
then renders the placeholder `embed.html` template. Real chat UI lands in
Step 6.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from main_ui.cookies import EMAIL_COOKIE_NAME
from main_ui.routes._validation import (
    DEFAULT_TUTOR,
    validate_course,
    validate_exercise,
    validate_tutor,
)


embed_bp = Blueprint("embed", __name__)


def _bad_param(err: dict):
    return jsonify({"error": "invalid_param", **err}), 404


@embed_bp.get("/embed")
def embed():
    course = request.args.get("course")
    exercise = request.args.get("exercise")
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

    tutor_config = {"course": course, "exercise": exercise, "tutor": tutor}
    has_email = bool(request.cookies.get(EMAIL_COOKIE_NAME))
    return render_template(
        "embed.html",
        course=course,
        exercise=exercise,
        tutor=tutor,
        tutor_config=tutor_config,
        has_email=has_email,
    )
