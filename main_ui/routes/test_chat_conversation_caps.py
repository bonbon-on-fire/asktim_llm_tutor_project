"""Flask test-client: stateful caps (message-count login, conversation ceiling).

Uses a throwaway sqlite DB and a monkeypatched tutor stream so no real LLM runs.
Run:
    python -m main_ui.routes.test_chat_conversation_caps
"""
from __future__ import annotations

import json
import os
import tempfile

# Point the app at a throwaway DB BEFORE importing it.
_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_DB_FD)
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["FREE_MESSAGES_BEFORE_LOGIN"] = "3"
os.environ["MAX_CONVERSATION_TOKENS"] = "225000"

from main_ui.run_app import app  # noqa: E402
from main_ui.db.models import Base  # noqa: E402
from main_ui.db import engine  # noqa: E402  (real engine, built from DATABASE_URL at import time)
from main_ui.cookies import USERNAME_COOKIE_NAME, sign_username  # noqa: E402
from main_ui.services import tutor_bridge  # noqa: E402

# `_validation.DEFAULT_COURSE` ("cities_and_climate_change") is stale/archived in
# this checkout's curriculum/ tree (only physics_iii_vibrations_and_waves and
# supply_chain_design are active) -- use a real, currently-active course+exercise
# so the turns actually get past validate_course/validate_selection and reach the
# gates under test.
COURSE = "supply_chain_design"
EXERCISE = "1"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def _fake_stream(new_tokens):
    def _gen(**kwargs):
        yield {"type": "delta", "text": "ok"}
        # Mirror the REAL bridge cost shape: per-call records at the top level
        # (keyed by call name), NOT nested under a "calls" wrapper. Using the
        # true shape here is what makes this a real regression guard for the
        # conversation ceiling — the wrapped shape silently summed to 0.
        yield {"type": "done", "reply": "ok", "reasoning": None, "retrieved": None,
               "cost": {"model": "m", "usd": 0.0, "tutor": {
                   "input_tokens": new_tokens, "output_tokens": 0, "cache_read": 0}}}
    return _gen


def _drain(resp):
    return b"".join(resp.response).decode("utf-8")


def _signed_username():
    # sign_username() reads current_app.secret_key, so it needs an app context.
    with app.app_context():
        return sign_username("tester")


def main() -> int:
    ok = True
    Base.metadata.create_all(engine)
    client = app.test_client()
    ex = EXERCISE

    # --- message-count login gate: 3 free, 4th blocked (no username cookie) ---
    tutor_bridge.stream_tutor_reply = _fake_stream(100)
    cid = None
    for i in range(3):
        body = {"text": f"m{i}", "course": COURSE, "exercise": ex}
        if cid:
            body["conversation_id"] = cid
        r = client.post("/api/chat", json=body)
        ok &= _check(f"free message {i+1} streams", r.status_code == 200, r.status_code)
        body_txt = _drain(r)
        for line in body_txt.splitlines():
            if line.startswith("data:") and "conversation_id" in line:
                cid = json.loads(line[5:]).get("conversation_id") or cid
    r = client.post("/api/chat", json={"text": "m4", "course": COURSE, "exercise": ex, "conversation_id": cid})
    ok &= _check("4th message blocked", r.status_code == 403, r.status_code)
    ok &= _check("4th -> login_required(message_count)",
                 r.get_json().get("error") == "login_required" and r.get_json().get("trigger") == "message_count",
                 r.get_json())

    # --- conversation ceiling: a huge-usage turn trips the next turn ---
    tutor_bridge.stream_tutor_reply = _fake_stream(300000)  # one turn > 225k
    client.set_cookie(USERNAME_COOKIE_NAME, _signed_username())
    r = client.post("/api/chat", json={"text": "big", "course": COURSE, "exercise": ex})
    ok &= _check("big message streams", r.status_code == 200, r.status_code)
    txt = _drain(r)
    cid2 = None
    for line in txt.splitlines():
        if line.startswith("data:") and "conversation_id" in line:
            cid2 = json.loads(line[5:]).get("conversation_id")
    ok &= _check("done reports conversation_tokens", "conversation_tokens" in txt, txt[-200:])
    r = client.post("/api/chat", json={"text": "again", "course": COURSE, "exercise": ex, "conversation_id": cid2})
    ok &= _check("over-ceiling next turn blocked", r.status_code == 403, r.status_code)
    ok &= _check("over-ceiling -> conversation_limit", r.get_json().get("error") == "conversation_limit", r.get_json())

    engine.dispose()
    try:
        os.remove(_DB_PATH)
    except OSError:
        pass  # Windows may still hold the file open via a pooled connection.
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
