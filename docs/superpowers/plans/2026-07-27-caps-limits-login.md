# Caps, Limits & Forced Login Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three production guards to `main_ui`: a per-message token cap, a per-conversation token ceiling, and forced login after 3 messages / before any upload.

**Architecture:** All enforcement is server-authoritative in the `POST /api/chat` handler, running **pre-stream** so a blocked turn writes nothing and the SSE contract is untouched. Per-message tokens are *estimated* from size (no tokenizer); per-conversation tokens are summed *post-hoc* from each tutor row's stored `usage_json`. Limits are env-tunable via `main_ui/config.py`. The browser mirrors the rules for instant feedback but the server is the authority.

**Tech Stack:** Python 3 / Flask / SQLAlchemy; vanilla JS front end. Tests are standalone `python -m <module>` scripts printing PASS/FAIL (repo convention — there is no pytest or JS harness).

## Global Constraints

- **Scope: `main_ui` only.** Do not touch `sandbox_ui` (intentionally uncapped). Shared code in `utils/` and `ui_core/` may be added to, but must not change sandbox_ui behavior.
- **Locked values (defaults):** per-message `10000` tokens, per-conversation `225000` tokens, `3` free messages before login. All env-overridable.
- **Token estimate constants:** `CHARS_PER_TOKEN = 4`, `TOKENS_PER_IMAGE = 1600`.
- **"New" (cost-relevant) tokens** per turn = `sum over calls of max(0, input_tokens - cache_read) + output_tokens`. Malformed/null `usage_json` counts as 0.
- **Login boundary:** first 3 student messages free; the **4th** (prior student-count ≥ 3) is blocked when no username cookie. Uploads require a username **always**.
- **Hard blocks, composer preserved.** Reuse the handler's existing pre-stream JSON-error shape (`{"error": <code>, "reason": ...}`).
- Conventional-commit messages; **no `Co-Authored-By: Claude` trailer**.
- Tests are standalone scripts: `def main() -> int` returning `0`/`1`, run via `python -m <dotted.path>`, with a `_check(label, ok, detail)` helper (see `main_ui/services/test_conversation_labels.py`).

---

### Task 1: Env-tunable limits in config

**Files:**
- Modify: `main_ui/config.py`
- Test: `main_ui/test_config_limits.py` (Create)

**Interfaces:**
- Produces: `Config.max_message_tokens: int`, `Config.max_conversation_tokens: int`, `Config.free_messages_before_login: int`, populated by `load_config()`.

- [ ] **Step 1: Write the failing test**

```python
# main_ui/test_config_limits.py
"""Standalone: main_ui config exposes env-tunable caps with locked defaults.

Run:
    python -m main_ui.test_config_limits
"""
from __future__ import annotations

import os
from main_ui.config import load_config


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    for k in ("MAX_MESSAGE_TOKENS", "MAX_CONVERSATION_TOKENS", "FREE_MESSAGES_BEFORE_LOGIN"):
        os.environ.pop(k, None)
    c = load_config()
    ok &= _check("default max_message_tokens", c.max_message_tokens == 10000, c.max_message_tokens)
    ok &= _check("default max_conversation_tokens", c.max_conversation_tokens == 225000, c.max_conversation_tokens)
    ok &= _check("default free_messages_before_login", c.free_messages_before_login == 3, c.free_messages_before_login)

    os.environ["MAX_MESSAGE_TOKENS"] = "5000"
    os.environ["MAX_CONVERSATION_TOKENS"] = "100000"
    os.environ["FREE_MESSAGES_BEFORE_LOGIN"] = "1"
    c = load_config()
    ok &= _check("env override max_message_tokens", c.max_message_tokens == 5000, c.max_message_tokens)
    ok &= _check("env override max_conversation_tokens", c.max_conversation_tokens == 100000, c.max_conversation_tokens)
    ok &= _check("env override free_messages_before_login", c.free_messages_before_login == 1, c.free_messages_before_login)
    for k in ("MAX_MESSAGE_TOKENS", "MAX_CONVERSATION_TOKENS", "FREE_MESSAGES_BEFORE_LOGIN"):
        os.environ.pop(k, None)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m main_ui.test_config_limits`
Expected: FAIL — `Config` has no attribute `max_message_tokens` (AttributeError) or FAIL lines.

- [ ] **Step 3: Add the three fields to `Config` and `load_config()`**

In `main_ui/config.py`, add to the `Config` dataclass (after `cookie_max_age_seconds`):
```python
    max_message_tokens: int
    max_conversation_tokens: int
    free_messages_before_login: int
```
In `load_config()`, before the `return Config(...)`, add:
```python
    max_message_tokens = int(os.environ.get("MAX_MESSAGE_TOKENS", "10000"))
    max_conversation_tokens = int(os.environ.get("MAX_CONVERSATION_TOKENS", "225000"))
    free_messages_before_login = int(os.environ.get("FREE_MESSAGES_BEFORE_LOGIN", "3"))
```
and pass them into the `Config(...)` constructor:
```python
        max_message_tokens=max_message_tokens,
        max_conversation_tokens=max_conversation_tokens,
        free_messages_before_login=free_messages_before_login,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m main_ui.test_config_limits`
Expected: all PASS, exit 0.

- [ ] **Step 5: Commit**

```bash
git add main_ui/config.py main_ui/test_config_limits.py
git commit -m "feat(main-ui): env-tunable message/conversation token caps and login threshold"
```

---

### Task 2: Per-message token estimator (pure)

**Files:**
- Create: `utils/tokens.py`
- Test: `utils/test_tokens.py` (Create)

**Interfaces:**
- Produces: `estimate_message_tokens(text: str, extracted_texts: list[str], n_images: int) -> int`; module constants `CHARS_PER_TOKEN = 4`, `TOKENS_PER_IMAGE = 1600`.

- [ ] **Step 1: Write the failing test**

```python
# utils/test_tokens.py
"""Standalone: per-message token estimate (text + files + images).

Run:
    python -m utils.test_tokens
"""
from __future__ import annotations

from utils.tokens import estimate_message_tokens, CHARS_PER_TOKEN, TOKENS_PER_IMAGE


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    ok &= _check("empty -> 0", estimate_message_tokens("", [], 0) == 0)
    ok &= _check("text ceil-div", estimate_message_tokens("a" * 9, [], 0) == 3, estimate_message_tokens("a" * 9, [], 0))  # ceil(9/4)=3
    ok &= _check("one image", estimate_message_tokens("", [], 1) == TOKENS_PER_IMAGE)
    ok &= _check("three images", estimate_message_tokens("", [], 3) == 3 * TOKENS_PER_IMAGE)
    ok &= _check(
        "mixed text+files+images",
        estimate_message_tokens("x" * 400, ["y" * 400], 2)
        == (800 // CHARS_PER_TOKEN) + 2 * TOKENS_PER_IMAGE,
        estimate_message_tokens("x" * 400, ["y" * 400], 2),
    )
    # A maxed legit message stays under 10k; a huge paste exceeds it.
    ok &= _check("maxed legit < 10k", estimate_message_tokens("t" * 4000, ["f" * 15000], 3) < 10000,
                 estimate_message_tokens("t" * 4000, ["f" * 15000], 3))
    ok &= _check("50k-char paste >= 10k", estimate_message_tokens("z" * 50000, [], 0) >= 10000,
                 estimate_message_tokens("z" * 50000, [], 0))
    ok &= _check("None-safe", estimate_message_tokens(None, [None], 0) == 0)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m utils.test_tokens`
Expected: FAIL — `ModuleNotFoundError: utils.tokens`.

- [ ] **Step 3: Write minimal implementation**

```python
# utils/tokens.py
"""Pure per-message token estimate for the chat composer cap.

No tokenizer is available in the repo, so this approximates: ~4 chars/token for
text (typed text + extracted attachment text) plus a flat conservative per-image
cost (~Claude's per-image maximum). Used server-side in the chat handler and
mirrored by the browser composer; keep the constants in sync with chat.js.
"""
from __future__ import annotations

CHARS_PER_TOKEN = 4
TOKENS_PER_IMAGE = 1600


def estimate_message_tokens(text: str, extracted_texts: list[str], n_images: int) -> int:
    """Estimate the token cost of one student message (text + files + images)."""
    chars = len(text or "") + sum(len(t or "") for t in (extracted_texts or []))
    text_tokens = -(-chars // CHARS_PER_TOKEN)  # ceil division
    return text_tokens + max(0, n_images) * TOKENS_PER_IMAGE
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m utils.test_tokens`
Expected: all PASS, exit 0.

- [ ] **Step 5: Commit**

```bash
git add utils/tokens.py utils/test_tokens.py
git commit -m "feat(utils): per-message token estimator (text + files + images)"
```

---

### Task 3: Per-conversation new-token sum

**Files:**
- Modify: `ui_core/usage.py` (add pure parser)
- Modify: `ui_core/services/conversation.py` (add sum function)
- Modify: `main_ui/services/conversation.py` (add thin wrapper; fix stale docstring reference)
- Modify: `ui_core/services/conversation.py` (fix `count_student_messages` docstring)
- Test: `main_ui/services/test_conversation_tokens.py` (Create)

**Interfaces:**
- Consumes: `Models` bundle (already defined), `messages.usage_json` column.
- Produces:
  - `ui_core.usage.new_tokens_from_usage_json(usage_json: str | None) -> int`
  - `ui_core.services.conversation.sum_conversation_new_tokens(db, conversation, *, models: Models) -> int`
  - `main_ui.services.conversation.sum_conversation_new_tokens(db, conversation) -> int`

- [ ] **Step 1: Write the failing test**

```python
# main_ui/services/test_conversation_tokens.py
"""Standalone: per-conversation new-token sum over stored usage_json.

Run:
    python -m main_ui.services.test_conversation_tokens
"""
from __future__ import annotations

import json
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from main_ui.db.models import Base
from main_ui.services import conversation as svc
from ui_core.usage import new_tokens_from_usage_json


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def _usage(**calls) -> str:
    return json.dumps({"usd": 0.0, "calls": calls})


def main() -> int:
    ok = True
    # Pure parser: new = max(0, input-cache_read)+output, summed across calls.
    u = _usage(
        tutor={"input_tokens": 30000, "output_tokens": 300, "cache_read": 28000},
        student={"input_tokens": 1000, "output_tokens": 20, "cache_read": 900},
    )
    ok &= _check("parser sums new tokens", new_tokens_from_usage_json(u) == (2000 + 300) + (100 + 20),
                 new_tokens_from_usage_json(u))
    ok &= _check("parser null -> 0", new_tokens_from_usage_json(None) == 0)
    ok &= _check("parser malformed -> 0", new_tokens_from_usage_json("{not json") == 0)
    ok &= _check("parser missing keys -> 0", new_tokens_from_usage_json(json.dumps({"calls": {"t": {}}})) == 0)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        convo = svc.find_or_create_conversation(
            s, session_id="a", conversation_id=None, course="supply_chain_design",
            exercise_number="7", exercise_kind="practice", tutor_prompt="tutor_07",
        )
        s.commit()
        # Two completed turns with known new-token contributions.
        for text, tokens in (("q1", 2300), ("q2", 4000)):
            svc.start_exchange_student_only(s, conversation=convo, student_text=text)
            svc.complete_exchange_tutor(
                s, conversation=convo, turn=convo_turn(s, convo),
                tutor_text="a", pedagogical_reasoning=None,
                usage_json=_usage(tutor={"input_tokens": tokens, "output_tokens": 0, "cache_read": 0}),
            )
        s.commit()
        total = svc.sum_conversation_new_tokens(s, convo)
        ok &= _check("conversation sum across turns", total == 2300 + 4000, total)
    return 0 if ok else 1


def convo_turn(s, convo):
    # Next turn number = current student-message count (turns are 1-based per pair).
    return svc.count_student_messages(s, convo)


if __name__ == "__main__":
    raise SystemExit(main())
```

> Note to implementer: confirm `complete_exchange_tutor`'s `turn` argument matches the `start_exchange_student_only` row's `turn`. If the pairing differs, capture the returned student row's `.turn` from `start_exchange_student_only` and pass that instead of the `convo_turn` helper. The assertion that matters is the **total**.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m main_ui.services.test_conversation_tokens`
Expected: FAIL — `ImportError: cannot import name 'new_tokens_from_usage_json'` (and `sum_conversation_new_tokens` missing).

- [ ] **Step 3: Implement the parser and sum**

In `ui_core/usage.py`, add:
```python
def new_tokens_from_usage_json(usage_json: str | None) -> int:
    """Cost-relevant ("new", non-cached) token count for one stored turn.

    ``usage_json`` is the tutor turn's cost dict: ``{"calls": {name: {input_tokens,
    output_tokens, cache_read}}}``. Per call, new tokens = ``max(0, input_tokens -
    cache_read) + output_tokens``; summed across calls. Returns 0 for a missing,
    empty, unparseable, or shape-unexpected value so a bad row never blocks a chat.
    """
    if not usage_json:
        return 0
    try:
        data = json.loads(usage_json)
    except (ValueError, TypeError):
        return 0
    calls = (data or {}).get("calls")
    if not isinstance(calls, dict):
        return 0
    total = 0
    for call in calls.values():
        if not isinstance(call, dict):
            continue
        inp = call.get("input_tokens") or 0
        out = call.get("output_tokens") or 0
        cache = call.get("cache_read") or 0
        total += max(0, inp - cache) + out
    return total
```

In `ui_core/services/conversation.py`, import the parser (extend the existing `from ui_core.usage import ...` line) and add:
```python
def sum_conversation_new_tokens(db: Session, conversation: Any, *, models: Models) -> int:
    """Cumulative cost-relevant tokens across a conversation's tutor rows.

    Sums :func:`ui_core.usage.new_tokens_from_usage_json` over every stored
    ``usage_json`` for the conversation. Reads only completed turns, so the
    running total lags the in-flight turn by one (see the caps design spec).
    """
    rows = db.execute(
        select(models.Message.usage_json).where(
            models.Message.conversation_id == conversation.id
        )
    ).scalars().all()
    return sum(new_tokens_from_usage_json(u) for u in rows)
```

Also fix the stale docstring in `count_student_messages` — replace the line
`Step 7's username modal triggers when this reaches 3.` with
`Used by the forced-login gate: once this reaches the free-message limit and no
username is set, the next turn is blocked (see main_ui chat handler).`

In `main_ui/services/conversation.py`, add the wrapper (near `count_student_messages`):
```python
def sum_conversation_new_tokens(db: Session, conversation: Conversation) -> int:
    """Cumulative cost-relevant tokens across this conversation's tutor rows."""
    return _shared.sum_conversation_new_tokens(db, conversation, models=_MODELS)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m main_ui.services.test_conversation_tokens`
Expected: all PASS, exit 0. Also re-run `python -m main_ui.services.test_conversation_labels` to confirm no regression.

- [ ] **Step 5: Commit**

```bash
git add ui_core/usage.py ui_core/services/conversation.py main_ui/services/conversation.py main_ui/services/test_conversation_tokens.py
git commit -m "feat(ui-core): per-conversation new-token sum from stored usage_json"
```

---

### Task 4: Stateless chat-handler gates (per-message cap + upload login)

**Files:**
- Modify: `main_ui/routes/chat.py`
- Test: `main_ui/routes/test_chat_caps.py` (Create)

**Interfaces:**
- Consumes: `load_config()`, `estimate_message_tokens`, `read_username_cookie`.
- Produces: two pre-stream JSON errors — `400 {"error":"message_too_long", ...}` and `403 {"error":"login_required","trigger":"attachment"}`.

- [ ] **Step 1: Write the failing test**

```python
# main_ui/routes/test_chat_caps.py
"""Flask test-client: stateless chat caps (per-message tokens, upload login).

Run:
    python -m main_ui.routes.test_chat_caps
"""
from __future__ import annotations

import io
from main_ui.run_app import app
from main_ui.routes._validation import DEFAULT_COURSE, list_exercise


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()
    exercises = list_exercise(DEFAULT_COURSE)
    ex = exercises[0] if exercises else "1"

    # Oversized text -> 400 message_too_long, before any course/DB work.
    r = client.post("/api/chat", json={
        "text": "z" * 60000, "course": DEFAULT_COURSE, "exercise": ex,
    })
    ok &= _check("huge text -> 400", r.status_code == 400, r.status_code)
    ok &= _check("huge text -> message_too_long", r.get_json().get("error") == "message_too_long", r.get_json())

    # A file upload with no username cookie -> 403 login_required.
    data = {
        "text": "here is my file",
        "course": DEFAULT_COURSE,
        "exercise": ex,
        "files": (io.BytesIO(b"col1,col2\n1,2\n"), "data.csv"),
    }
    r = client.post("/api/chat", data=data, content_type="multipart/form-data")
    ok &= _check("upload logged-out -> 403", r.status_code == 403, r.status_code)
    ok &= _check("upload logged-out -> login_required", r.get_json().get("error") == "login_required", r.get_json())

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

> Note to implementer: if `list_exercise` is not the exact validator export, use whatever `_validation` exposes for exercise numbers (mirror `test_chat_practice.py`'s `list_practice`). The gates fire before selection validation, so even a wrong `ex` still returns the cap/login error — but keep a plausible value.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m main_ui.routes.test_chat_caps`
Expected: FAIL — huge text currently streams/validates (not 400 `message_too_long`); upload logged-out is not blocked.

- [ ] **Step 3: Wire the two stateless gates**

In `main_ui/routes/chat.py`:

Add imports:
```python
from main_ui.config import load_config
from utils.tokens import estimate_message_tokens
```

Add a helper near `_bad_request`:
```python
def _login_required(trigger: str):
    """403 JSON telling the client to open the (mandatory) username modal."""
    return jsonify({"error": "login_required", "trigger": trigger}), 403
```

After the `enforce_combined_cap(...)` block and the `if not text and not images and not attachments:` check (i.e. once `text`, `images`, `attachments` are known — around line 143), insert:
```python
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
```

Then **remove the later** `username = read_username_cookie(request)` assignment (currently around line 178) since it now runs above. Leave the `db = g.pop("db")` line where it is.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m main_ui.routes.test_chat_caps`
Expected: all PASS, exit 0. Re-run `python -m main_ui.routes.test_chat_practice` to confirm no regression.

- [ ] **Step 5: Commit**

```bash
git add main_ui/routes/chat.py main_ui/routes/test_chat_caps.py
git commit -m "feat(main-ui): per-message token cap and upload-login gate on /api/chat"
```

---

### Task 5: Stateful chat-handler gates (message-count login + conversation ceiling) + done-event fields

**Files:**
- Modify: `main_ui/routes/chat.py`
- Test: `main_ui/routes/test_chat_conversation_caps.py` (Create)

**Interfaces:**
- Consumes: `count_student_messages`, `sum_conversation_new_tokens`, `load_config()`.
- Produces: `403 {"error":"login_required","trigger":"message_count"}`; `403 {"error":"conversation_limit", ...}`; `done` event gains `conversation_tokens` and `conversation_limit_reached`.

- [ ] **Step 1: Write the failing test**

```python
# main_ui/routes/test_chat_conversation_caps.py
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
from main_ui.db.engine import engine  # noqa: E402  (adjust import to the app's engine)
from main_ui.services import tutor_bridge  # noqa: E402
from main_ui.routes._validation import DEFAULT_COURSE, list_exercise  # noqa: E402


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def _fake_stream(new_tokens):
    def _gen(**kwargs):
        yield {"type": "delta", "text": "ok"}
        yield {"type": "done", "reply": "ok", "reasoning": None, "retrieved": None,
               "cost": {"usd": 0.0, "calls": {"tutor": {
                   "input_tokens": new_tokens, "output_tokens": 0, "cache_read": 0}}}}
    return _gen


def _drain(resp):
    return b"".join(resp.response).decode("utf-8")


def main() -> int:
    ok = True
    Base.metadata.create_all(engine)
    client = app.test_client()
    ex = (list_exercise(DEFAULT_COURSE) or ["1"])[0]

    # --- message-count login gate: 3 free, 4th blocked (no username cookie) ---
    tutor_bridge.stream_tutor_reply = _fake_stream(100)
    cid = None
    for i in range(3):
        body = {"text": f"m{i}", "course": DEFAULT_COURSE, "exercise": ex}
        if cid:
            body["conversation_id"] = cid
        r = client.post("/api/chat", json=body)
        ok &= _check(f"free message {i+1} streams", r.status_code == 200, r.status_code)
        body_txt = _drain(r)
        for line in body_txt.splitlines():
            if line.startswith("data:") and "conversation_id" in line:
                cid = json.loads(line[5:]).get("conversation_id") or cid
    r = client.post("/api/chat", json={"text": "m4", "course": DEFAULT_COURSE, "exercise": ex, "conversation_id": cid})
    ok &= _check("4th message blocked", r.status_code == 403, r.status_code)
    ok &= _check("4th -> login_required(message_count)",
                 r.get_json().get("error") == "login_required" and r.get_json().get("trigger") == "message_count",
                 r.get_json())

    # --- conversation ceiling: a huge-usage turn trips the next turn ---
    tutor_bridge.stream_tutor_reply = _fake_stream(300000)  # one turn > 225k
    with client.session_transaction():
        pass
    client.set_cookie("localhost", "tutor_username", _signed_username())  # helper below
    r = client.post("/api/chat", json={"text": "big", "course": DEFAULT_COURSE, "exercise": ex})
    txt = _drain(r)
    cid2 = None
    for line in txt.splitlines():
        if line.startswith("data:") and "conversation_id" in line:
            cid2 = json.loads(line[5:]).get("conversation_id")
    ok &= _check("done reports conversation_tokens", "conversation_tokens" in txt, txt[-200:])
    r = client.post("/api/chat", json={"text": "again", "course": DEFAULT_COURSE, "exercise": ex, "conversation_id": cid2})
    ok &= _check("over-ceiling next turn blocked", r.status_code == 403, r.status_code)
    ok &= _check("over-ceiling -> conversation_limit", r.get_json().get("error") == "conversation_limit", r.get_json())

    os.remove(_DB_PATH)
    return 0 if ok else 1


def _signed_username():
    from main_ui.cookies import sign_username
    return sign_username("tester")


if __name__ == "__main__":
    raise SystemExit(main())
```

> Notes to implementer (resolve while implementing — do NOT leave placeholders):
> - Fix the engine import to the app's actual engine/session accessor (grep `create_engine` / `sessionmaker` under `main_ui/db/`). If tables are created via the app on first request instead, call that instead of `create_all`.
> - `client.set_cookie` signature differs across Werkzeug versions; use the form the installed version accepts (grep other tests, or `client.set_cookie("tutor_username", val)`).
> - The cookie name constant is `USERNAME_COOKIE_NAME` (from `main_ui.cookies`) — use it rather than the literal if it differs.
> - The message-count turns run **without** a username cookie; the ceiling turns run **with** one (so only the ceiling, not the login gate, blocks them).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m main_ui.routes.test_chat_conversation_caps`
Expected: FAIL — 4th message still streams; no `conversation_tokens` in `done`; over-ceiling turn not blocked.

- [ ] **Step 3: Wire the stateful gates and done-event fields**

In `main_ui/routes/chat.py`, extend the imports from `main_ui.services.conversation` to include `sum_conversation_new_tokens`.

Immediately **after** `find_or_create_conversation(...)` returns `convo` (after the `except WrongSessionError` block, before the `history = get_history_for_tutor(...)` snapshot), insert:
```python
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
```

In the `event_stream()` generator, after `student_count = count_student_messages(db, convo_obj)` and before/at the `done` emit, compute and include the token total:
```python
                conversation_tokens = sum_conversation_new_tokens(db, convo_obj)
```
and add to the `done` payload dict:
```python
                    "conversation_tokens": conversation_tokens,
                    "conversation_limit_reached": conversation_tokens >= load_config().max_conversation_tokens,
```
(Reuse the `config` already loaded above if it is still in scope in the generator's closure; if not, call `load_config()` as shown.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m main_ui.routes.test_chat_conversation_caps`
Expected: all PASS, exit 0. Re-run `python -m main_ui.routes.test_chat_caps` and `python -m main_ui.routes.test_chat_practice`.

- [ ] **Step 5: Commit**

```bash
git add main_ui/routes/chat.py main_ui/routes/test_chat_conversation_caps.py
git commit -m "feat(main-ui): forced-login threshold, conversation token ceiling, usage in done event"
```

---

### Task 6: Client mirror (composer cap, mandatory login, conversation-limit lockout)

**Files:**
- Modify: `main_ui/static/js/chat.js`
- Verify: manual browser check (no JS test harness in the repo)

**Interfaces:**
- Consumes (from `done` SSE): `student_message_count`, `conversation_tokens`, `conversation_limit_reached`, and the pre-stream JSON errors `message_too_long` / `login_required` / `conversation_limit`.

> Read `main_ui/static/js/chat.js` fully first. Anchor points from the current file: the upload-mirror constants near the top (`MAX_IMAGE_BYTES`, `MAX_FILE_BYTES`, `MAX_ATTACHMENTS_PER_MESSAGE`, ~lines 15–24); `maybeShowEmailModal` (~lines 496–503); `studentMessageCount` state (~line 987); `formatEntryHeader` (label logic, unrelated). Match the file's existing style (no framework, direct DOM).

- [ ] **Step 1: Add mirrored estimate constants + helper**

Next to the existing upload-mirror constants, add (keep in sync with `utils/tokens.py`):
```js
// Mirror of utils/tokens.py — keep constants identical.
const CHARS_PER_TOKEN = 4;
const TOKENS_PER_IMAGE = 1600;
const MAX_MESSAGE_TOKENS = 10000;      // mirror of config default
function estimateMessageTokens(text, extractedChars, nImages) {
  const chars = (text ? text.length : 0) + (extractedChars || 0);
  return Math.ceil(chars / CHARS_PER_TOKEN) + Math.max(0, nImages) * TOKENS_PER_IMAGE;
}
```
Note: the browser cannot cheaply know a file's *extracted* text length pre-upload; use the file's byte size as a conservative proxy for `extractedChars` (bytes ≈ chars for text; over-counts binary, which only makes the guard stricter). This is a UX pre-check only — the server estimate on real extracted text is authoritative.

- [ ] **Step 2: Enforce the per-message cap in the composer**

In the send/submit handler, before dispatching the request, compute the estimate from the current text, attached files' sizes, and image count. If `>= MAX_MESSAGE_TOKENS`, block send and show inline text "That message is too long. Shorten it or split it across turns." Do **not** clear the composer. (Optionally also disable the send button live on input.)

- [ ] **Step 3: Make login mandatory (replace the nudge)**

Replace the `maybeShowEmailModal` nudge behavior so that:
- When `student_message_count >= 3` (read from the `done` event), the next send is gated: open the username modal in a **non-dismissible** mode (no backdrop-close / no skip button) and block sending until the username cookie is set.
- When the user tries to attach a file/image while logged out, open the same mandatory modal and cancel the attach/send.
- On a server `403 login_required` response to a send, open the mandatory modal (authoritative fallback). Use the `trigger` field only to tailor copy ("Log in to attach files or images." vs "Log in to keep chatting.").

Keep the existing identity POST flow; only the modal's mandatory/dismissible behavior and trigger change.

- [ ] **Step 4: Conversation-limit lockout**

When a `done` event has `conversation_limit_reached === true`, disable the composer (textarea + send + attach) and show "This chat reached its length limit — start a new chat to continue." Also handle a server `403 conversation_limit` on send the same way (fallback). Provide/keep the existing "new chat" affordance as the escape.

- [ ] **Step 5: Manual verification**

Start the app locally and verify in a browser (or via the embed smoke path used previously):
```bash
# from repo root, with env set as usual:
python -m main_ui.run_app
```
Checklist (record PASS/FAIL in the commit message body):
- Paste ~60k characters → send is blocked with the too-long message; composer text preserved.
- Send 3 messages logged out → 4th attempt opens a non-dismissible login modal; sending is blocked until a username is set.
- Attach a file logged out → mandatory modal opens; no send occurs.
- Simulate the ceiling by setting `MAX_CONVERSATION_TOKENS=500` and sending one turn → next turn is locked out with the length-limit message and a "new chat" path.

- [ ] **Step 6: Commit**

```bash
git add main_ui/static/js/chat.js
git commit -m "feat(main-ui): composer token cap, mandatory login modal, conversation-limit lockout"
```

---

## Notes for the executor

- **Env vars for tests:** Tasks 1 and 5 mutate `os.environ`. They pop the keys they set on the way out; if you run tests in one process, run Task 5's script last or in a fresh process (it repoints `DATABASE_URL`).
- **Post-hoc lag is intended:** the conversation ceiling blocks the turn *after* the one that crosses 225k. The per-message cap (Task 4) is the real-time backstop. Do not try to pre-count the in-flight turn's tokens — there is no tokenizer.
- **Do not touch `sandbox_ui`.** If a shared change in `ui_core`/`utils` would alter sandbox behavior, stop and flag it.
- After all tasks: run every new/affected standalone test, then use superpowers:finishing-a-development-branch.
