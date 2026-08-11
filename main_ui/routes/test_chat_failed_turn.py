"""A failed tutor turn is surfaced as an SSE error frame and persists no tutor row.

When the tutor can't produce a valid answer, the bridge's ``done`` event carries
``failed: True`` (empty reply or the canned parse-failure fallback). The chat
route must then emit ``event: error`` — so the client shows "Tap to retry" —
instead of a ``done`` frame, and must NOT write a tutor Message row. A normal
reply still yields ``done`` and persists the tutor row.

Uses a throwaway sqlite DB and a monkeypatched tutor stream so no real LLM runs
(mirrors main_ui/routes/test_chat_stream_error_logging.py's harness).

Run:
    python -m main_ui.routes.test_chat_failed_turn
"""
from __future__ import annotations

import os
import tempfile

# Point the app at a throwaway DB BEFORE importing it.
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_DB_FD)
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

from main_ui.run_app import app  # noqa: E402
from main_ui.db.models import Base, Message  # noqa: E402
from main_ui.db import engine, SessionLocal  # noqa: E402
from main_ui.services import tutor_bridge  # noqa: E402
from tutor.run_tutor import INVALID_RESPONSE_ANSWER  # noqa: E402

COURSE = "supply_chain_design"
EXERCISE = "1"


def _failed_stream(**kwargs):
    # Bridge signals a failed turn: the canned fallback answer plus failed=True.
    yield {"type": "done", "reply": INVALID_RESPONSE_ANSWER, "reasoning": None, "failed": True}


def _ok_stream(**kwargs):
    yield {"type": "delta", "text": "Here"}
    yield {"type": "done", "reply": "Here is a hint.", "reasoning": "r", "failed": False}


def _drain(resp):
    return b"".join(resp.response).decode("utf-8")


def _tutor_row_count():
    with SessionLocal() as s:
        return s.query(Message).filter(Message.role == "tutor").count()


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    Base.metadata.create_all(engine)
    client = app.test_client()

    # --- Failed turn: error frame, no done, no tutor row persisted. ---
    tutor_bridge.stream_tutor_reply = _failed_stream  # type: ignore[assignment]
    resp = client.post(
        "/api/chat", json={"text": "hi", "course": COURSE, "exercise": EXERCISE}
    )
    body = _drain(resp)
    ok &= _check("failed turn emits event: error", "event: error" in body, body)
    ok &= _check("failed turn emits no event: done", "event: done" not in body, body)
    ok &= _check(
        "failed turn does not stream the canned fallback text",
        INVALID_RESPONSE_ANSWER not in body,
        body,
    )
    ok &= _check(
        "failed turn persists no tutor row", _tutor_row_count() == 0, _tutor_row_count()
    )

    # --- Success turn: done frame, tutor row persisted. ---
    tutor_bridge.stream_tutor_reply = _ok_stream  # type: ignore[assignment]
    resp = client.post(
        "/api/chat", json={"text": "hi again", "course": COURSE, "exercise": EXERCISE}
    )
    body = _drain(resp)
    ok &= _check("success turn emits event: done", "event: done" in body, body)
    ok &= _check(
        "success turn persists one tutor row", _tutor_row_count() == 1, _tutor_row_count()
    )

    engine.dispose()
    try:
        os.remove(_DB_PATH)
    except OSError:
        pass  # Windows may still hold the file open via a pooled connection.
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
