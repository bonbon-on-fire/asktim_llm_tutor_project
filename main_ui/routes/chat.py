"""POST /api/chat — accept a student text message, persist the exchange,
and return the tutor's reply.

JSON request:
    {
      "text": "...",                    required, non-empty
      "course": "...",                  required
      "exercise": "NN",                 required, zero-padded 2-digit
      "tutor": "tutor_05",              optional, defaults to tutor_05
      "conversation_id": "<uuid>"       optional; absent = create new
    }

JSON response (200):
    {
      "conversation_id": "<uuid>",
      "reply": "...",
      "student_message_count": <int>
    }

Errors: 400 bad text or bad conversation_id format; 404 bad course/exercise/
tutor; 403 conversation_id not owned by the current session; 502 tutor call
failed or returned empty.
"""

from __future__ import annotations

from uuid import UUID

from flask import Blueprint, g, jsonify, request

from main_ui.cookies import EMAIL_COOKIE_NAME
from main_ui.routes._validation import (
    DEFAULT_TUTOR,
    validate_course,
    validate_exercise,
    validate_tutor,
)
from main_ui.services import tutor_bridge
from main_ui.services.conversation import (
    WrongSessionError,
    append_exchange,
    count_student_messages,
    find_or_create_conversation,
    get_history_for_tutor,
)


chat_bp = Blueprint("chat", __name__)


def _bad_param(err: dict):
    return jsonify({"error": "invalid_param", **err}), 404


def _bad_request(reason: str, error_code: str = "bad_request"):
    return jsonify({"error": error_code, "reason": reason}), 400


def _wrong_session():
    return (
        jsonify(
            {
                "error": "wrong_session",
                "reason": "conversation not found or not owned by this session",
            }
        ),
        403,
    )


def _tutor_failed(reason: str):
    return jsonify({"error": "tutor_failed", "reason": reason}), 502


@chat_bp.post("/api/chat")
def chat():
    data = request.get_json(silent=True) or {}

    text = (data.get("text") or "").strip()
    if not text:
        return _bad_request("text must be a non-empty string", "missing_text")

    course = data.get("course")
    exercise = data.get("exercise")
    tutor = data.get("tutor") or DEFAULT_TUTOR

    err = validate_course(course)
    if err:
        return _bad_param(err)
    err = validate_exercise(course, exercise)
    if err:
        return _bad_param(err)
    err = validate_tutor(tutor)
    if err:
        return _bad_param(err)

    convo_id_raw = data.get("conversation_id")
    convo_id: UUID | None = None
    if convo_id_raw is not None:
        try:
            convo_id = UUID(str(convo_id_raw))
        except (ValueError, TypeError):
            return _bad_request(
                "conversation_id must be a UUID string", "bad_conversation_id"
            )

    db = g.db
    email = request.cookies.get(EMAIL_COOKIE_NAME)

    try:
        convo = find_or_create_conversation(
            db,
            session_id=g.session_id,
            conversation_id=convo_id,
            course=course,
            exercise_number=exercise,
            tutor_prompt=tutor,
            email=email,
        )
    except WrongSessionError:
        return _wrong_session()

    # When reusing an existing conversation, use its stored course/exercise/tutor
    # for the LLM call rather than the request's. Defends against a misbehaving
    # frontend silently switching the LLM context mid-conversation.
    history = get_history_for_tutor(db, convo)

    try:
        reply = tutor_bridge.get_tutor_reply(
            course=convo.course,
            exercise=convo.exercise_number,
            tutor=convo.tutor_prompt,
            history=history,
            new_student_message=text,
        )
    except Exception as exc:
        return _tutor_failed(f"{type(exc).__name__}: {exc}")

    reply_text = reply.get("reply") or ""
    if not reply_text:
        return _tutor_failed("empty reply from tutor")

    append_exchange(
        db,
        conversation=convo,
        student_text=text,
        tutor_text=reply_text,
        pedagogical_reasoning=reply.get("reasoning"),
    )

    student_count = count_student_messages(db, convo)

    return jsonify(
        {
            "conversation_id": str(convo.id),
            "reply": reply_text,
            "student_message_count": student_count,
        }
    )
