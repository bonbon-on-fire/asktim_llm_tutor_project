"""POST /api/chat — accept a student text message, stream the tutor's reply
back as Server-Sent Events, and persist the exchange.

JSON request:
    {
      "text": "...",                    required, non-empty
      "course": "...",                  required
      "exercise": "N",                  required, non-padded integer
      "tutor": "tutor_06",              optional, defaults to tutor_06
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

from sandbox_ui.cookies import USERNAME_COOKIE_NAME
from sandbox_ui.routes._validation import (
    DEFAULT_TUTOR,
    validate_course,
    validate_selection,
    validate_tutor,
)
from sandbox_ui.services import files as files_service
from sandbox_ui.services import images as images_service
from sandbox_ui.services import tutor_bridge
from sandbox_ui.services.conversation import (
    WrongSessionError,
    complete_exchange_tutor,
    count_student_messages,
    find_or_create_conversation,
    get_history_for_tutor,
    start_exchange_student_only,
)
from utils.attachments import (
    AttachmentExtractionError,
    AttachmentValidationError,
    EmptyExtractionError,
)
from utils.uploads import UploadValidationError, enforce_combined_cap, images_to_tuples


chat_bp = Blueprint("chat", __name__)


def _bad_param(err: dict):
    """Build a 404 JSON response for an invalid course/exercise/tutor param."""
    return jsonify({"error": "invalid_param", **err}), 404


def _bad_request(reason: str, error_code: str = "bad_request"):
    """Build a 400 JSON response with the given error code and reason."""
    return jsonify({"error": error_code, "reason": reason}), 400


def _wrong_session():
    """Build a 403 JSON response for a conversation not owned by this session."""
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
    """Handle a chat turn: validate input, persist the student message, and stream the tutor reply as SSE.

    Accepts multipart/form-data (text plus image uploads) or legacy JSON
    (text only). Starts or continues a conversation, then returns a streaming
    Server-Sent Events response of the tutor's reply.
    """
    # Accept multipart/form-data (text + image files) or legacy JSON (text only).
    is_multipart = (request.content_type or "").startswith("multipart/form-data")
    if is_multipart:
        src = request.form
        upload_files = request.files.getlist("images")
        upload_docs = request.files.getlist("files")
    else:
        src = request.get_json(silent=True) or {}
        upload_files = []
        upload_docs = []

    text = (src.get("text") or "").strip()

    # Validate uploads up front so a bad file fails cleanly before any DB write.
    try:
        images = images_service.read_and_validate(upload_files)
    except UploadValidationError as exc:
        return _bad_request(str(exc), "bad_image")

    try:
        attachments = files_service.read_and_validate(upload_docs)
    except AttachmentValidationError as exc:
        return _bad_request(str(exc), "bad_file")
    except EmptyExtractionError as exc:
        return _bad_request(str(exc), "empty_extraction")
    except AttachmentExtractionError as exc:
        return _bad_request(str(exc), "extraction_failed")

    try:
        enforce_combined_cap(len(images), len(attachments))
    except UploadValidationError as exc:
        return _bad_request(str(exc), "too_many_attachments")

    if not text and not images and not attachments:
        return _bad_request("text or an attachment is required", "missing_text")
    # Image/file-only turns get a placeholder so the bubble/history read cleanly
    # and the non-student-like guard (which checks the text portion) doesn't fire.
    student_text = text or ("(File attached.)" if attachments else "(Image attached.)")

    course = src.get("course")
    exercise = src.get("exercise")
    raw_kind = src.get("exercise_kind")
    exercise_kind = "practice" if str(raw_kind).strip().lower() == "practice" else "exercise"
    tutor = src.get("tutor") or DEFAULT_TUTOR
    # sandbox_ui context switch: syllabus defaults ON (matches main_ui) unless the
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

    # Same shape as syllabus: whether the course lectures/*.txt transcripts are
    # folded into context. Defaults ON; "No lectures" in the wizard sends it off.
    raw_lectures = src.get("lectures")
    if raw_lectures is None:
        lectures_enabled = True
    elif isinstance(raw_lectures, str):
        lectures_enabled = raw_lectures.strip().lower() not in {"0", "false", "no", "off", ""}
    else:
        lectures_enabled = bool(raw_lectures)

    # Same shape as syllabus: whether the built-in course.txt description is
    # folded into context. Defaults ON; "No course description" in the wizard
    # sends it off. Only honored when creating a new convo.
    raw_course_enabled = src.get("course_enabled")
    if raw_course_enabled is None:
        course_enabled = True
    elif isinstance(raw_course_enabled, str):
        course_enabled = raw_course_enabled.strip().lower() not in {"0", "false", "no", "off", ""}
    else:
        course_enabled = bool(raw_course_enabled)

    # One-off custom context from the "Create context" wizard. A non-None value
    # means "use this text verbatim instead of the on-disk file" for that field.
    custom_course_text = src.get("course_custom")
    custom_exercise_text = src.get("exercise_custom")
    custom_tutor_prompt = src.get("tutor_custom")
    custom_syllabus_text = src.get("syllabus_custom")
    custom_lectures_text = src.get("lectures_custom")

    # sandbox_ui RAG toggle: per-conversation context mode ("rag" | "full_context").
    # None = let the bridge resolve by default (rag when the course has an index).
    # Only honored when creating a new conversation; continuations replay it.
    context_mode = src.get("context_mode")
    if context_mode is not None:
        context_mode = str(context_mode).strip().lower() or None

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
            err = validate_selection(course, exercise, exercise_kind)
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
    username = request.cookies.get(USERNAME_COOKIE_NAME)

    def _abort_with(json_response):
        """Roll back and close the DB session, then return json_response."""
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
            exercise_kind=exercise_kind,
            tutor_prompt=tutor,
            username=username,
            course_enabled=course_enabled,
            syllabus_enabled=syllabus_enabled,
            lectures_enabled=lectures_enabled,
            custom_course_text=custom_course_text,
            custom_exercise_text=custom_exercise_text,
            custom_tutor_prompt=custom_tutor_prompt,
            custom_syllabus_text=custom_syllabus_text,
            custom_lectures_text=custom_lectures_text,
            context_mode=context_mode,
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
    # together with the student message below. Surface storage/schema problems as
    # a clean JSON reason rather than an opaque 500 (e.g. a pre-existing Sandbox
    # DB missing the uploaded_images.data column — run
    # `python -m sandbox_ui.db.reset_uploaded_images`).
    if images:
        try:
            images_service.persist_images(db, message=student_msg, images=images)
        except Exception as exc:
            return _abort_with(
                (
                    jsonify(
                        {
                            "error": "image_persist_failed",
                            "reason": f"{type(exc).__name__}: {exc}",
                        }
                    ),
                    500,
                )
            )

    # Persist uploaded non-image files linked to the student row, same shape as
    # the image persist path above.
    if attachments:
        try:
            files_service.persist_files(db, message=student_msg, files=attachments)
        except Exception as exc:
            return _abort_with(
                (
                    jsonify(
                        {
                            "error": "file_persist_failed",
                            "reason": f"{type(exc).__name__}: {exc}",
                        }
                    ),
                    500,
                )
            )

    # Capture all values we'll need inside the generator BEFORE commit, since
    # SQLAlchemy expires loaded attributes on commit by default.
    convo_id_str = str(convo.id)
    stream_course = convo.course
    stream_exercise = convo.exercise_number
    # Legacy rows predating this column read back NULL; treat as "exercise".
    stream_exercise_kind = convo.exercise_kind or "exercise"
    stream_tutor = convo.tutor_prompt
    # Legacy rows predating this column read back NULL; treat that as ON so
    # continuing an old conversation keeps the course description it had.
    stream_course_enabled = convo.course_enabled is None or bool(convo.course_enabled)
    stream_syllabus = convo.syllabus_enabled
    # Legacy rows predating this column read back NULL; treat as ON.
    stream_lectures = convo.lectures_enabled is None or bool(convo.lectures_enabled)
    stream_course_text = convo.custom_course_text
    stream_exercise_text = convo.custom_exercise_text
    stream_custom_tutor_prompt = convo.custom_tutor_prompt
    stream_syllabus_text = convo.custom_syllabus_text
    stream_lectures_text = convo.custom_lectures_text
    stream_context_mode = convo.context_mode

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
        exercise_kind=stream_exercise_kind,
        tutor=stream_tutor,
        history=history,
        new_student_message=student_text + files_service.files_to_text(attachments),
        images=images_to_tuples(images),
        include_course=stream_course_enabled,
        include_syllabus=stream_syllabus,
        include_lectures=stream_lectures,
        course_text=stream_course_text,
        exercise_text=stream_exercise_text,
        syllabus_text=stream_syllabus_text,
        lectures_text=stream_lectures_text,
        custom_tutor_prompt=stream_custom_tutor_prompt,
        context_mode=stream_context_mode,
    )

    def event_stream():
        """Stream the tutor reply as SSE frames, persisting the completed exchange when done."""
        full_reply = ""
        reasoning = None
        retrieved = None  # per-turn RAG records: [{source, score, chars, text}]
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
                        retrieved = ev.get("retrieved") or None
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
                    retrieved_context=(
                        json.dumps(retrieved, ensure_ascii=False) if retrieved else None
                    ),
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
                    # Sandbox is a dev/TA tool — surface the tutor's hidden
                    # reasoning so it can be inspected per message as we chat.
                    "pedagogical_reasoning": reasoning,
                    # Also surface what RAG retrieved this turn (may be None).
                    "retrieved": retrieved,
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
