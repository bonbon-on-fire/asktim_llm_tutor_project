"""Regression: a tutor-stream exception is logged server-side (not silently swallowed).

Root cause of the toym26 incident: main_ui/routes/chat.py caught the tutor-stream
exception, emitted an SSE `event: error` frame, and returned WITHOUT logging, so the
failure was invisible in Railway logs. This asserts the log record is now written.

Uses a throwaway sqlite DB and a monkeypatched tutor stream so no real LLM runs
(mirrors main_ui/routes/test_chat_conversation_caps.py's harness).

Run:
    python -m main_ui.routes.test_chat_stream_error_logging
"""
from __future__ import annotations

import logging
import os
import tempfile

# Point the app at a throwaway DB BEFORE importing it.
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_DB_FD)
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"

from main_ui.run_app import app  # noqa: E402
from main_ui.db.models import Base  # noqa: E402
from main_ui.db import engine  # noqa: E402  (real engine, built from DATABASE_URL at import time)
from main_ui.services import tutor_bridge  # noqa: E402

COURSE = "supply_chain_design"
EXERCISE = "1"


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.records: list[logging.LogRecord] = []

    def emit(self, record):
        self.records.append(record)


def _boom(**kwargs):
    # A generator that raises on first advance: mimics the tutor stream failing
    # inside the `for ev in stream_tutor_reply(...)` loop in event_stream().
    raise RuntimeError("boom-transient-xyz")
    yield  # unreachable; marks this as a generator so calling it returns an iterator


def _drain(resp):
    return b"".join(resp.response).decode("utf-8")


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    Base.metadata.create_all(engine)
    tutor_bridge.stream_tutor_reply = _boom  # type: ignore[assignment]

    cap = _Capture()
    app.logger.addHandler(cap)
    try:
        client = app.test_client()
        resp = client.post(
            "/api/chat",
            json={"text": "hi", "course": COURSE, "exercise": EXERCISE},
        )
        body = _drain(resp)
    finally:
        app.logger.removeHandler(cap)

    # Client still gets the error frame (unchanged behavior).
    ok &= _check("event: error still emitted", "event: error" in body, body)
    # NEW: the exception was logged with traceback context.
    matched = [
        r for r in cap.records
        if r.exc_info and "boom-transient-xyz" in str(r.exc_info[1])
    ]
    ok &= _check(
        "exception logged with exc_info",
        bool(matched),
        f"got: {[r.getMessage() for r in cap.records]}",
    )

    engine.dispose()
    try:
        os.remove(_DB_PATH)
    except OSError:
        pass  # Windows may still hold the file open via a pooled connection.
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
