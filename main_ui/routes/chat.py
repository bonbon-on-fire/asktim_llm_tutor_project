"""POST /api/chat — accept a student text message, stream the tutor's reply
back as Server-Sent Events, and persist the exchange.

JSON request:
    {
      "text": "...",                    required, non-empty
      "course": "...",                  required
      "exercise": "N",                  required, non-padded integer
      "tutor": "tutor_07",              optional, defaults to tutor_07
      "conversation_id": "<uuid>"       optional; absent = create new
    }

Success response: ``text/event-stream`` with these events, in order:
    event: delta\n
    data: {"text": "..."}\n\n
    ...
    event: done\n
    data: {"conversation_id": "...", "reply": "...", "student_message_count": N,
           "tutor_message_id": <int>, "conversation_tokens": N,
           "conversation_limit_reached": bool}\n\n

Mid-stream failure:
    event: error\n
    data: {"reason": "..."}\n\n

Pre-stream failures still return JSON: 400 bad text or bad conversation_id;
404 bad course/exercise/tutor; 403 conversation_id not owned by the current
session, forced login past the free-message threshold
(``{"error":"login_required","trigger":"message_count"}``), or the
per-conversation token ceiling reached (``{"error":"conversation_limit", ...}``).
"""

from __future__ import annotations

import json
from uuid import UUID

from flask import Blueprint, Response, g, jsonify, request, stream_with_context

from main_ui.config import load_config
from main_ui.cookies import read_username_cookie
from main_ui.routes._validation import (
    DEFAULT_TUTOR,
    validate_course,
    validate_selection,
    validate_tutor,
)
from main_ui.services import files as files_service
from main_ui.services import images as images_service
from main_ui.services import tutor_bridge
from main_ui.services.conversation import (
    WrongSessionError,
    complete_exchange_tutor,
    count_student_messages,
    find_or_create_conversation,
    get_cached_history_for_tutor,
    get_history_for_tutor,
    start_exchange_student_only,
    sum_conversation_new_tokens,
)
from ui_core.tutor_bridge import cached_history_enabled
from utils.attachments import (
    AttachmentExtractionError,
    AttachmentValidationError,
    EmptyExtractionError,
)
from utils.tokens import estimate_message_tokens
from utils.uploads import UploadValidationError, enforce_combined_cap, images_to_tuples


chat_bp = Blueprint("chat", __name__)


def _bad_param(err: dict):
    """Build a 404 JSON response for a validation-failure dict."""
    return jsonify({"error": "invalid_param", **err}), 404


def _bad_request(reason: str, error_code: str = "bad_request"):
    """Build a 400 JSON response with the given error code and reason."""
    return jsonify({"error": error_code, "reason": reason}), 400


def _login_required(trigger: str):
    """403 JSON telling the client to open the (mandatory) username modal."""
    return jsonify({"error": "login_required", "trigger": trigger}), 403


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
    """Validate a chat turn, persist the student message, and stream the tutor reply as SSE.

    Handles multipart (text plus images) or JSON (text only) requests. Returns a
    JSON error before streaming on bad input, unknown course/exercise/tutor, a
    conversation not owned by this session, or a persistence failure; otherwise
    returns a ``text/event-stream`` response.
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

    config = load_config()

    # Per-message token cap (text + extracted file text + images). Estimated —
    # no tokenizer — and enforced before any DB work so a huge paste fails fast.
    est_tokens = estimate_message_tokens(
        text, [a.extracted_text for a in attachments], len(images)
    )
    if est_tokens >= config.max_message_tokens:
        return _bad_request(
            "That message is too long. Shorten it or split it across turns.",
            "message_too_long",
        )

    # Uploads require a logged-in username, regardless of message count.
    username = read_username_cookie(request)
    if (images or attachments) and not username:
        return _login_required("attachment")

    course = src.get("course")
    exercise = src.get("exercise")
    raw_kind = src.get("exercise_kind")
    exercise_kind = "practice" if str(raw_kind).strip().lower() == "practice" else "exercise"
    # Production is locked to a single tutor prompt: ignore any client-supplied
    # tutor and always use DEFAULT_TUTOR.
    tutor = DEFAULT_TUTOR

    err = validate_course(course)
    if err:
        return _bad_param(err)
    err = validate_selection(course, exercise, exercise_kind)
    if err:
        return _bad_param(err)
    err = validate_tutor(tutor)
    if err:
        return _bad_param(err)

    convo_id_raw = src.get("conversation_id")
    convo_id: UUID | None = None
    if convo_id_raw is not None:
        try:
            convo_id = UUID(str(convo_id_raw))
        except (ValueError, TypeError):
            return _bad_request(
                "conversation_id must be a UUID string", "bad_conversation_id"
            )

    # Take ownership of the request's DB session — teardown_request would
    # otherwise commit + close it the instant this view returns the Response,
    # well before the streaming generator runs its INSERTs. We commit
    # explicitly inside the generator instead.
    db = g.pop("db")

    def _abort_with(json_response):
        """Roll back and close the manually-owned DB session, then return *json_response*."""
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
        )
    except WrongSessionError:
        return _abort_with(_wrong_session())

    # Forced login: first N student messages free, then a username is required.
    prior_student_count = count_student_messages(db, convo)
    if not username and prior_student_count >= config.free_messages_before_login:
        return _abort_with(_login_required("message_count"))

    # Per-conversation token ceiling (post-hoc: reflects completed turns only).
    if sum_conversation_new_tokens(db, convo) >= config.max_conversation_tokens:
        return _abort_with(
            (
                jsonify(
                    {
                        "error": "conversation_limit",
                        "reason": "This chat reached its length limit — start a new chat to continue.",
                    }
                ),
                403,
            )
        )

    # Snapshot the prior turns BEFORE we insert this turn's student message,
    # so the tutor gets the same shape of history it always has.
    history = get_history_for_tutor(db, convo)
    stream_history_mode = "cached" if cached_history_enabled() else "legacy"
    cached_history = (
        get_cached_history_for_tutor(db, convo)
        if stream_history_mode == "cached"
        else []
    )

    # Insert the student row up front and commit it. That way the student's
    # message survives even if the tutor stream errors out partway through.
    student_msg = start_exchange_student_only(
        db, conversation=convo, student_text=student_text
    )
    student_turn = student_msg.turn

    # Persist uploaded images linked to the student row (bytes in-DB). Committed
    # together with the student message below, so a mid-stream tutor failure
    # still leaves the student turn + its images intact. Surface storage/schema
    # problems as a clean JSON reason rather than an opaque 500.
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
    stream_tutor = convo.tutor_prompt
    stream_exercise_kind = convo.exercise_kind or "exercise"

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
        history_mode=stream_history_mode,
        cached_history=cached_history,
    )

    def event_stream():
        """Generate SSE frames: stream tutor deltas, persist the reply, emit done/error."""
        full_reply = ""
        reasoning = None
        retrieved = None  # per-turn RAG records: [{source, score, chars, text}]
        cost = None  # {model, usd, ...} — estimated turn cost (persisted, not rendered)
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
                        cost = ev.get("cost") or None
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

            cost_usd = cost.get("usd") if cost else None
            usage_json = json.dumps(cost, ensure_ascii=False) if cost else None
            try:
                convo_obj = db.get(type(convo), convo.id)
                tutor_msg = complete_exchange_tutor(
                    db,
                    conversation=convo_obj,
                    turn=student_turn,
                    tutor_text=full_reply,
                    pedagogical_reasoning=reasoning,
                    retrieved_context=(json.dumps(retrieved, ensure_ascii=False) if retrieved else None),
                    cost_usd=cost_usd,
                    usage_json=usage_json,
                )
                # Capture the tutor row's id before commit expires the attribute,
                # so the client can rate this message via POST /api/message/<id>/rating.
                tutor_message_id = tutor_msg.id
                student_count = count_student_messages(db, convo_obj)
                conversation_tokens = sum_conversation_new_tokens(db, convo_obj)
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
                    # Message id of this tutor turn, so the client can thumb it.
                    "tutor_message_id": tutor_message_id,
                    "conversation_tokens": conversation_tokens,
                    "conversation_limit_reached": conversation_tokens >= config.max_conversation_tokens,
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
