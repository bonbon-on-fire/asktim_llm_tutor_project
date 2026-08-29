"""End-to-end: automatic outage detection through the real HTTP surface.

Drives POST /api/chat (with a monkeypatched tutor stream so no real LLM runs),
then checks that the shared service_health state, the /health/detail endpoint,
and the server-rendered "AskTIM is down" overlay all move together:

  * infra failures below threshold record but do NOT trip the banner
  * hitting the threshold trips degraded -> overlay renders (data-auto-degraded)
    and /health/detail reports it
  * a successful turn clears it -> overlay gone, /health/detail healthy
  * all three /api/chat failure points feed the recorder (stream exception,
    failed/empty reply, persist failure)
  * /health/detail reports db:"fail" when the DB read throws

Time-based lazy expiry is covered deterministically in
main_ui/services/test_service_health.py (injected ``now``); here recovery is
exercised via the realistic success path.

Uses a throwaway sqlite DB and the same harness as
main_ui/routes/test_chat_failed_turn.py.

Run:
    python -m main_ui.routes.test_outage_integration
"""
from __future__ import annotations

import os
import tempfile

# Point the app at a throwaway DB and pin outage config BEFORE importing the app.
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_DB_FD)
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["MAIN_UI_SECRET_KEY"] = "test"
# Trip after 3 failures (proves the env -> config -> recorder wiring too), never
# gate on free-message login in this test, and disable the per-worker read cache
# so each render/endpoint read reflects state immediately (deterministic).
os.environ["OUTAGE_FAILURE_THRESHOLD"] = "3"
os.environ["OUTAGE_HEALTH_CACHE_SECONDS"] = "0"
os.environ["FREE_MESSAGES_BEFORE_LOGIN"] = "100000"

from main_ui.run_app import app  # noqa: E402
from main_ui.db.models import Base, ServiceHealth  # noqa: E402
from main_ui.db import engine, SessionLocal  # noqa: E402
from main_ui.routes import chat as chat_route  # noqa: E402
from main_ui.routes import health as health_route  # noqa: E402
from main_ui.services import tutor_bridge  # noqa: E402
from tutor.run_tutor import INVALID_RESPONSE_ANSWER  # noqa: E402

COURSE = "supply_chain_design"
EXERCISE = "1"

_ORIG_COMPLETE = chat_route.complete_exchange_tutor
_ORIG_HEALTH_SESSION = health_route.SessionLocal


def _ok_stream(**kwargs):
    yield {"type": "delta", "text": "Here"}
    yield {"type": "done", "reply": "Here is a hint.", "reasoning": "r", "failed": False}


def _failed_stream(**kwargs):
    # done with failed=True -> route emits an error frame, records a failure.
    yield {"type": "done", "reply": INVALID_RESPONSE_ANSWER, "reasoning": None, "failed": True}


def _raising_stream(**kwargs):
    # Exception mid-stream -> route logs, emits error frame, records a failure.
    yield {"type": "delta", "text": "part"}
    raise RuntimeError("tutor pipeline exploded")


def _drain(resp):
    return b"".join(resp.response).decode("utf-8")


def _post(client):
    return client.post(
        "/api/chat", json={"text": "hi", "course": COURSE, "exercise": EXERCISE}
    )


def _health_row():
    with SessionLocal() as s:
        row = s.get(ServiceHealth, 1)
        if row is None:
            return None, None
        return bool(row.degraded), int(row.consecutive_failures)


def _detail(client):
    return client.get("/health/detail").get_json()


def _overlay_state(client):
    html = client.get("/").get_data(as_text=True)
    return ("maintenance-overlay" in html, 'data-auto-degraded="true"' in html)


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    Base.metadata.create_all(engine)
    client = app.test_client()

    # ---- A. Below threshold: failures record but do NOT trip. ----
    tutor_bridge.stream_tutor_reply = _failed_stream  # type: ignore[assignment]
    for _ in range(2):
        _drain(_post(client))
    degraded, cf = _health_row()
    ok &= _check("2 failures: recorded, not degraded", degraded is False and cf == 2, f"{degraded},{cf}")
    present, auto = _overlay_state(client)
    ok &= _check("below threshold: no overlay rendered", not present, present)
    d = _detail(client)
    ok &= _check("health/detail below threshold: healthy",
                 d["db"] == "ok" and d["degraded"] is False and d["consecutive_failures"] == 2, d)

    # ---- B. Reaching threshold trips degraded. ----
    _drain(_post(client))  # 3rd failure
    degraded, cf = _health_row()
    ok &= _check("3rd failure trips degraded", degraded is True and cf == 3, f"{degraded},{cf}")
    present, auto = _overlay_state(client)
    ok &= _check("degraded: overlay rendered", present, present)
    ok &= _check("degraded: overlay marked data-auto-degraded", auto, auto)
    d = _detail(client)
    ok &= _check("health/detail degraded shape",
                 d["db"] == "ok" and d["degraded"] is True and d["degraded_since"] is not None, d)

    # ---- C. A successful turn clears everything. ----
    tutor_bridge.stream_tutor_reply = _ok_stream  # type: ignore[assignment]
    body = _drain(_post(client))
    ok &= _check("success emits done frame", "event: done" in body, body)
    degraded, cf = _health_row()
    ok &= _check("success clears degraded + resets streak", degraded is False and cf == 0, f"{degraded},{cf}")
    present, auto = _overlay_state(client)
    ok &= _check("recovered: no overlay rendered", not present, present)
    d = _detail(client)
    ok &= _check("health/detail recovered: healthy",
                 d["degraded"] is False and d["consecutive_failures"] == 0, d)

    # ---- D. Stream-exception failure point feeds the recorder. ----
    tutor_bridge.stream_tutor_reply = _raising_stream  # type: ignore[assignment]
    for _ in range(3):
        body = _drain(_post(client))
    ok &= _check("stream exception emits error frame", "event: error" in body, body)
    degraded, cf = _health_row()
    ok &= _check("stream-exception path re-trips degraded", degraded is True and cf == 3, f"{degraded},{cf}")

    # clear again for the next isolated check
    tutor_bridge.stream_tutor_reply = _ok_stream  # type: ignore[assignment]
    _drain(_post(client))
    degraded, cf = _health_row()
    ok &= _check("cleared before persist-fail check", degraded is False and cf == 0, f"{degraded},{cf}")

    # ---- E. Persist-failure point feeds the recorder. ----
    def _boom(*a, **k):
        raise RuntimeError("db write blew up")

    chat_route.complete_exchange_tutor = _boom  # type: ignore[assignment]
    try:
        body = _drain(_post(client))
        ok &= _check("persist failure emits error frame", "event: error" in body and "persist_failed" in body, body)
        degraded, cf = _health_row()
        ok &= _check("persist-failure path records a failure", cf == 1, f"{degraded},{cf}")
    finally:
        chat_route.complete_exchange_tutor = _ORIG_COMPLETE  # type: ignore[assignment]

    # ---- F. /health/detail reports db:"fail" when the DB read throws. ----
    class _BoomSession:
        def execute(self, *a, **k):
            raise RuntimeError("connection refused")

        def rollback(self):
            pass

        def close(self):
            pass

    health_route.SessionLocal = lambda: _BoomSession()  # type: ignore[assignment]
    try:
        d = _detail(client)
        ok &= _check("health/detail db-fail shape",
                     d["db"] == "fail" and d["status"] == "degraded", d)
    finally:
        health_route.SessionLocal = _ORIG_HEALTH_SESSION  # type: ignore[assignment]

    # ---- G. Pre-stream infra failure (before streaming) feeds the recorder. ----
    # Reset to a clean, healthy row first.
    tutor_bridge.stream_tutor_reply = _ok_stream  # type: ignore[assignment]
    _drain(_post(client))
    degraded, cf = _health_row()
    ok &= _check("cleared before pre-stream-failure check", degraded is False and cf == 0, f"{degraded},{cf}")

    _orig_find = chat_route.find_or_create_conversation

    def _find_boom(*a, **k):
        raise RuntimeError("conversation store unreachable")

    chat_route.find_or_create_conversation = _find_boom  # type: ignore[assignment]
    try:
        resp = _post(client)
        body = resp.get_data(as_text=True)
        ok &= _check("pre-stream infra failure returns 500 conversation_failed",
                     resp.status_code == 500 and "conversation_failed" in body,
                     f"{resp.status_code} :: {body}")
        degraded, cf = _health_row()
        ok &= _check("pre-stream infra failure records a failure", cf == 1, f"{degraded},{cf}")
    finally:
        chat_route.find_or_create_conversation = _orig_find  # type: ignore[assignment]

    # ---- H. A user-facing limit (forced login) must NOT record a failure. ----
    # Clear the streak, then force the login gate via a high prior-message count.
    _drain(_post(client))  # _ok_stream still installed -> success clears streak
    degraded, cf = _health_row()
    ok &= _check("cleared before user-error check", degraded is False and cf == 0, f"{degraded},{cf}")

    _orig_count = chat_route.count_student_messages
    chat_route.count_student_messages = lambda *a, **k: 10 ** 9  # type: ignore[assignment]
    try:
        resp = _post(client)  # no username -> login_required (user error, not infra)
        body = resp.get_data(as_text=True)
        ok &= _check("forced-login is a user error (not 500)",
                     resp.status_code in (401, 403) and "login" in body.lower(),
                     f"{resp.status_code} :: {body}")
        degraded, cf = _health_row()
        ok &= _check("user error does NOT record a failure", cf == 0, f"{degraded},{cf}")
    finally:
        chat_route.count_student_messages = _orig_count  # type: ignore[assignment]

    engine.dispose()
    try:
        os.remove(_DB_PATH)
    except OSError:
        pass  # Windows may still hold the file open via a pooled connection.
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
