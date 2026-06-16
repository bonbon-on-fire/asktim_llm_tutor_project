"""POST /api/chat — accept a student text message, stream the tutor's reply
back as Server-Sent Events, and persist the exchange.

JSON request:
    {
      "text": "...",                    required, non-empty
      "course": "...",                  required
      "exercise": "NN",                 required, zero-padded 2-digit
      "tutor": "tutor_05",              optional, defaults to tutor_05
      "conversation_id": "<uuid>"       optional; absent = create new
    }

Success response: ``text/event-stream`` with these events, in order:
    event: delta\n
    data: {"text": "..."}\n\n
    ...
    event: done\n
    data: {"conversation_id": "...", "reply": "...", "student_message_count": N}\n\n

Mid-stream failure:
    event: error\n
    data: {"reason": "..."}\n\n

Pre-stream failures still return JSON: 400 bad text or bad conversation_id;
404 bad course/exercise/tutor; 403 conversation_id not owned by the current
session; 502 if the tutor never even starts.
"""

from __future__ import annotations

import json
from uuid import UUID

from flask import Blueprint, Response, g, jsonify, request, stream_with_context

from test_ui.cookies import EMAIL_COOKIE_NAME
from test_ui.routes._validation import (
    DEFAULT_TUTOR,
    validate_course,
    validate_exercise,
    validate_tutor,
)
from test_ui.services import images as images_service
from test_ui.services import tutor_bridge
from test_ui.services.conversation import (
    WrongSessionError,
    complete_exchange_tutor,
    count_student_messages,
    find_or_create_conversation,
    get_history_for_tutor,
    start_exchange_student_only,
)
from utils.uploads import UploadValidationError, images_to_tuples


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


def _sse_event(name: str, payload: dict) -> str:
    """Serialize one SSE event frame: ``event: name\\ndata: {...}\\n\\n``."""
    data = json.dumps(payload, ensure_ascii=False)
    return f"event: {name}\ndata: {data}\n\n"


@chat_bp.post("/api/chat")
def chat():
    # Accept multipart/form-data (text + image files) or legacy JSON (text only).
    is_multipart = (request.content_type or "").startswith("multipart/form-data")
    if is_multipart:
        src = request.form
        upload_files = request.files.getlist("images")
    else:
        src = request.get_json(silent=True) or {}
        upload_files = []

    text = (src.get("text") or "").strip()

    # Validate uploads up front so a bad file fails cleanly before any DB write.
    try:
        images = images_service.read_and_validate(upload_files)
    except UploadValidationError as exc:
        return _bad_request(str(exc), "bad_image")

    if not text and not images:
        return _bad_request("text or an image is required", "missing_text")
    # Image-only turns get a placeholder so the bubble/history read cleanly and
    # the non-student-like guard (which checks the text portion) doesn't fire.
    student_text = text or "(Image attached.)"

    course = src.get("course")
    exercise = src.get("exercise")
    tutor = src.get("tutor") or DEFAULT_TUTOR
    # test_ui context switch: syllabus defaults ON (matches main_ui) unless the
    # request explicitly turns it off. Only applies when creating a new convo;
    # existing conversations keep their stored flag. Multipart sends the flag as
    # a string ("true"/"false"); JSON sends a real bool.
    raw_syllabus = src.get("syllabus")
    if raw_syllabus is None:
        syllabus_enabled = True
    elif isinstance(raw_syllabus, str):
        syllabus_enabled = raw_syllabus.strip().lower() not in {"0", "false", "no", "off", ""}
    else:
        syllabus_enabled = bool(raw_syllabus)

    # One-off custom context from the "Create context" wizard. A non-None value
    # means "use this text verbatim instead of the on-disk file" for that field.
    custom_course_text = src.get("course_custom")
    custom_exercise_text = src.get("exercise_custom")
    custom_tutor_prompt = src.get("tutor_custom")
    custom_syllabus_text = src.get("syllabus_custom")

    convo_id_raw = src.get("conversation_id")
    convo_id: UUID | None = None
    if convo_id_raw is not None:
        try:
            convo_id = UUID(str(convo_id_raw))
        except (ValueError, TypeError):
            return _bad_request(
                "conversation_id must be a UUID string", "bad_conversation_id"
            )

    # Validate the requested context only when STARTING a new conversation.
    # Continuations replay the conversation's stored (already-validated)
    # context, so placeholder ids like "custom" must not be re-validated.
    # Custom fields skip file-based validation; built-in fields still validate.
    if convo_id is None:
        if custom_course_text is None:
            err = validate_course(course)
            if err:
                return _bad_param(err)
        else:
            course = "custom"

        if custom_exercise_text is None:
            if custom_course_text is not None:
                return _bad_request(
                    "provide exercise_custom when the course is custom",
                    "exercise_requires_course",
                )
            err = validate_exercise(course, exercise)
            if err:
                return _bad_param(err)
        else:
            exercise = "custom"

        if custom_tutor_prompt is None:
            err = validate_tutor(tutor)
            if err:
                return _bad_param(err)
        else:
            tutor = "custom"

    # Take ownership of the request's DB session — teardown_request would
    # otherwise commit + close it the instant this view returns the Response,
    # well before the streaming generator runs its INSERTs. We commit
    # explicitly inside the generator instead.
    db = g.pop("db")
    email = request.cookies.get(EMAIL_COOKIE_NAME)

    def _abort_with(json_response):
        # Helper for the validation-failure path: roll back any pending
        # writes and close the session before returning the JSON error.
        try:
            db.rollback()
        finally:
            db.close()
        return json_response

    try:
        convo = find_or_create_conversation(
            db,
            session_id=g.session_id,
            conversation_id=convo_id,
            course=course,
            exercise_number=exercise,
            tutor_prompt=tutor,
            email=email,
            syllabus_enabled=syllabus_enabled,
            custom_course_text=custom_course_text,
            custom_exercise_text=custom_exercise_text,
            custom_tutor_prompt=custom_tutor_prompt,
            custom_syllabus_text=custom_syllabus_text,
        )
    except WrongSessionError:
        return _abort_with(_wrong_session())

    # Snapshot the prior turns BEFORE we insert this turn's student message,
    # so the tutor gets the same shape of history it always has.
    history = get_history_for_tutor(db, convo)

    # Insert the student row up front and commit it. That way the student's
    # message survives even if the tutor stream errors out partway through.
    student_msg = start_exchange_student_only(
        db, conversation=convo, student_text=student_text
    )
    student_turn = student_msg.turn

    # Persist uploaded images linked to the student row (bytes in-DB), committed
    # together with the student message below.
    if images:
        images_service.persist_images(db, message=student_msg, images=images)

    # Capture all values we'll need inside the generator BEFORE commit, since
    # SQLAlchemy expires loaded attributes on commit by default.
    convo_id_str = str(convo.id)
    stream_course = convo.course
    stream_exercise = convo.exercise_number
    stream_tutor = convo.tutor_prompt
    stream_syllabus = convo.syllabus_enabled
    stream_course_text = convo.custom_course_text
    stream_exercise_text = convo.custom_exercise_text
    stream_custom_tutor_prompt = convo.custom_tutor_prompt
    stream_syllabus_text = convo.custom_syllabus_text

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        db.close()
        return jsonify(
            {"error": "persist_failed", "reason": f"{type(exc).__name__}: {exc}"}
        ), 500

    # When reusing an existing conversation, use its stored course/exercise/
    # tutor for the LLM call rather than the request's — defends against a
    # misbehaving frontend silently switching the LLM context mid-conversation.
    stream_kwargs = dict(
        course=stream_course,
        exercise=stream_exercise,
        tutor=stream_tutor,
        history=history,
        new_student_message=student_text,
        images=images_to_tuples(images),
        include_syllabus=stream_syllabus,
        course_text=stream_course_text,
        exercise_text=stream_exercise_text,
        syllabus_text=stream_syllabus_text,
        custom_tutor_prompt=stream_custom_tutor_prompt,
    )

    def event_stream():
        full_reply = ""
        reasoning = None
        try:
            try:
                for ev in tutor_bridge.stream_tutor_reply(**stream_kwargs):
                    ev_type = ev.get("type")
                    if ev_type == "delta":
                        piece = ev.get("text", "")
                        if piece:
                            full_reply += piece
                            yield _sse_event("delta", {"text": piece})
                    elif ev_type == "done":
                        # The 'done' event from the bridge carries the
                        # authoritative parsed reply (post-normalization).
                        # Prefer it over the delta-concatenated string.
                        if ev.get("reply"):
                            full_reply = ev["reply"]
                        reasoning = ev.get("reasoning")
                        break
            except Exception as exc:
                yield _sse_event(
                    "error", {"reason": f"{type(exc).__name__}: {exc}"}
                )
                return

            if not full_reply:
                yield _sse_event(
                    "error", {"reason": "empty reply from tutor"}
                )
                return

            try:
                convo_obj = db.get(type(convo), convo.id)
                complete_exchange_tutor(
                    db,
                    conversation=convo_obj,
                    turn=student_turn,
                    tutor_text=full_reply,
                    pedagogical_reasoning=reasoning,
                )
                student_count = count_student_messages(db, convo_obj)
                db.commit()
            except Exception as exc:
                db.rollback()
                yield _sse_event(
                    "error",
                    {"reason": f"persist_failed: {type(exc).__name__}: {exc}"},
                )
                return

            yield _sse_event(
                "done",
                {
                    "conversation_id": convo_id_str,
                    "reply": full_reply,
                    "student_message_count": student_count,
                },
            )
        finally:
            db.close()

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            # Tell nginx (if ever proxied) not to buffer the response.
            "X-Accel-Buffering": "no",
        },
    )
