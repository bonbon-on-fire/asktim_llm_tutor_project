# Tutor Failure Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make transient Anthropic model-API failures diagnosable, self-healing, and non-destructive in the chat UI, so students stop silently losing turns and blindly resending.

**Architecture:** Three independent, individually-deployable fixes to the tutor streaming path. (1) Server logs the swallowed tutor-stream exception. (2) The raw Anthropic streamer retries transient 429/5xx/connection errors with bounded backoff *before* the first visible delta. (3) The chat frontend preserves the student's message on failure and offers an explicit Retry instead of deleting the bubble and silently restoring the composer text.

**Tech Stack:** Python 3 / Flask (`current_app.logger`), `anthropic` SDK 0.105.2 (raw `client.messages.stream`), SQLAlchemy 2.x, vanilla JS (`main_ui/static/js/chat.js`), Jinja2 templates. Tests are plain runnable modules (`python -m <pkg>.<module>` with a `__main__` block) that also expose `pytest`-discoverable `test_*` functions.

## Background (root cause — already investigated)

Student `toym26` sent the same message 7× on 2026-07-29 ~20:07–20:11 UTC with no tutor reply. Evidence established the cause was a **transient Anthropic model-API error** (rate-limit / overloaded class) inside `stream_tutor_reply_anthropic_raw`, surfaced to the browser as a 195-byte SSE `event: error` frame. No deploy occurred at incident time; the exact request replays successfully now (proving it was transient); the token cap was not involved (~25k vs 450k ceiling). Two aggravating mechanics turned one transient blip into 7 lost turns:

- **No server log:** [chat.py:363-367](../../../main_ui/routes/chat.py#L363-L367) catches the exception, emits an `event: error` SSE frame, and returns — but never logs it, so the failure was undiagnosable from Railway logs.
- **Destructive frontend:** [chat.js:1140-1147](../../../main_ui/static/js/chat.js#L1140-L1147) on error removes the tutor bubble **and** the student bubble, restores the text into the composer, and shows a generic banner. The student sees their message vanish and the text reappear → presses Enter again → repeat.

## Global Constraints

- **Commit messages:** Conventional Commits — `type(scope): subject`. Applies to every commit including merges.
- **No AI co-author trailer:** Do NOT add `Co-Authored-By: Claude` (or any AI co-author) to commits.
- **Branch:** Work on `prod-beta-plus` (current branch). Do not push or deploy unless the user asks — the user deploys these one-by-one.
- **anthropic SDK:** 0.105.2. Available exception classes (all confirmed present): `RateLimitError`, `InternalServerError`, `APITimeoutError`, `APIConnectionError`, `APIStatusError`, `APIError`.
- **Logging:** The repo has no app-wide logging framework. The only pattern is Flask `current_app.logger.error("... %s", exc)` / `current_app.logger.exception("...")` (see [database.py:123,133](../../../database_ui/routes/database.py#L123)). Use exactly that.
- **Tests:** Plain modules, no shared conftest. Each test file monkeypatches its dependency and either runs under `pytest` or via a `__main__` block printing `PASS`. Match the neighbor files' style (`tutor/test_stream_thinking_disabled.py`, `tutor/test_run_tutor_json_mode.py`, `main_ui/routes/test_chat_conversation_caps.py`).
- **Deploy order:** Task 1 → Task 2 → Task 3, each deployed and observed before the next. Tasks are independent; nothing later depends on earlier code.

---

## Task 1: Log the swallowed tutor-stream exception (server)

The smallest, safest fix — pure observability, zero behavior change for the client. Deploy first so the next incident is diagnosable and so we can confirm Task 2's retries in production logs.

**Files:**
- Modify: `main_ui/routes/chat.py` — add `current_app` to the flask import ([chat.py:38](../../../main_ui/routes/chat.py#L38)); add a log call inside the exception handler ([chat.py:363-367](../../../main_ui/routes/chat.py#L363-L367)).
- Test: `main_ui/routes/test_chat_stream_error_logging.py` (create)

**Interfaces:**
- Consumes: existing `tutor_bridge.stream_tutor_reply(**stream_kwargs)` call in `event_stream()`; existing `_sse_event(name, payload)` helper.
- Produces: a `current_app.logger.exception(...)` ERROR log record whenever the tutor stream raises, carrying `exc_info`. No change to the SSE bytes sent to the client.

- [ ] **Step 1: Write the failing test**

Create `main_ui/routes/test_chat_stream_error_logging.py`. This mirrors the throwaway-sqlite + `test_client` pattern of `test_chat_conversation_caps.py` (set `DATABASE_URL` to a temp sqlite file **before** importing the app), and attaches a capturing handler to `app.logger` to assert the exception is logged while the `event: error` frame is still emitted.

```python
"""Regression: a tutor-stream exception is logged server-side (not silently swallowed).

Root cause of the toym26 incident: main_ui/routes/chat.py caught the tutor-stream
exception, emitted an SSE `event: error` frame, and returned WITHOUT logging, so the
failure was invisible in Railway logs. This asserts the log record is now written.

Run:
    python -m main_ui.routes.test_chat_stream_error_logging
"""
from __future__ import annotations

import logging
import os
import tempfile

_DB_FD, _DB_PATH = tempfile.mkstemp(suffix=".db")
os.close(_DB_FD)
os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")

from main_ui.app import app  # noqa: E402  (import after DATABASE_URL is set)
from main_ui.db.models import Base  # noqa: E402
from main_ui.db.session import engine  # noqa: E402
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


def _drain(resp) -> str:
    return b"".join(resp.response).decode("utf-8")


def test_tutor_stream_exception_is_logged():
    Base.metadata.create_all(engine)
    tutor_bridge.stream_tutor_reply = _boom  # type: ignore[assignment]

    cap = _Capture()
    app.logger.addHandler(cap)
    try:
        client = app.test_client()
        resp = client.post(
            "/api/chat",
            json={"text": "hi", "course": COURSE, "exercise": EXERCISE, "tutor": "on"},
        )
        body = _drain(resp)
    finally:
        app.logger.removeHandler(cap)

    # Client still gets the error frame (unchanged behavior).
    assert "event: error" in body, body
    # NEW: the exception was logged with traceback context.
    matched = [
        r for r in cap.records
        if r.exc_info and "boom-transient-xyz" in str(r.exc_info[1])
    ]
    assert matched, f"expected a logged exception record, got: {[r.getMessage() for r in cap.records]}"


if __name__ == "__main__":
    test_tutor_stream_exception_is_logged()
    print("PASS - tutor stream exception is logged")
```

> Note: confirm the app import path (`main_ui.app:app`), the models `Base`, the engine module, and the `/api/chat` field names against `main_ui/routes/test_chat_conversation_caps.py` before running — copy that file's exact imports and request shape if any name differs. The test's *intent* (capture an ERROR record with `exc_info` carrying the raised message) is what matters.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m main_ui.routes.test_chat_stream_error_logging`
Expected: FAIL — an `AssertionError: expected a logged exception record, got: [...]` (the current code emits the SSE frame but logs nothing).

- [ ] **Step 3: Add the `current_app` import**

In [chat.py:38](../../../main_ui/routes/chat.py#L38), add `current_app` to the existing flask import:

```python
from flask import Blueprint, Response, current_app, g, jsonify, request, stream_with_context
```

- [ ] **Step 4: Log the exception in the handler**

In `event_stream()` at [chat.py:363-367](../../../main_ui/routes/chat.py#L363-L367), add the log call before yielding the error frame:

```python
            except Exception as exc:
                current_app.logger.exception("tutor stream failed: %s", exc)
                yield _sse_event(
                    "error", {"reason": f"{type(exc).__name__}: {exc}"}
                )
                return
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m main_ui.routes.test_chat_stream_error_logging`
Expected: `PASS - tutor stream exception is logged`

- [ ] **Step 6: Commit**

```bash
git add main_ui/routes/chat.py main_ui/routes/test_chat_stream_error_logging.py
git commit -m "fix(chat): log swallowed tutor-stream exception server-side"
```

---

## Task 2: Retry transient Anthropic errors with bounded backoff (server)

The actual healing fix. Retry the stream **only before the first visible delta is yielded** — once bytes have reached the client we cannot restart. Reset the `StudentAnswerExtractor` on each attempt so a partially-fed extractor never leaks across retries.

**Files:**
- Modify: `tutor/run_tutor.py` — add `import time` ([run_tutor.py:15](../../../tutor/run_tutor.py#L15) area); add retry constants near the other module constants (`_MAX_MSG_BREAKPOINTS`/`_CACHE_EVERY` live ~line 893); wrap the streaming body of `stream_tutor_reply_anthropic_raw` ([run_tutor.py:1023-1080](../../../tutor/run_tutor.py#L1023-L1080)) in a retry loop.
- Test: `tutor/test_stream_retry.py` (create)

**Interfaces:**
- Consumes: `anthropic.RateLimitError`, `anthropic.InternalServerError`, `anthropic.APITimeoutError`, `anthropic.APIConnectionError`; existing `StudentAnswerExtractor`, `build_anthropic_request`, `anthropic_tool_kwargs`, `json_mode_enabled`, `_tool_input_from_message`, `_normalize_tutor_ai_message`, `_anthropic_usage_message`.
- Produces: same generator contract as before — visible `str` chunks then `("__done__", normalized_text, usage_msg)`. New module-level names: `_RETRYABLE_ANTHROPIC_ERRORS: tuple`, `_MAX_STREAM_RETRIES: int = 2`, `_RETRY_BASE_DELAY: float = 0.5`, and a helper `_retry_backoff_seconds(attempt: int) -> float` returning `_RETRY_BASE_DELAY * (2 ** (attempt - 1))`.

**Design notes (read before implementing):**
- Retry happens when the exception is raised **before any visible delta was yielded** (typically at stream entry / first read for 429/529/connection errors). If `yielded_any` is already `True`, re-raise immediately — a partial answer is already on the wire.
- The extractor and `final_message` are re-initialized at the top of each attempt so nothing carries over.
- After exhausting retries, re-raise the last exception; the caller ([chat.py](../../../main_ui/routes/chat.py) / Task 1) logs it and emits the error frame — that's the correct terminal behavior.
- Bounded, small backoff (2 retries → 0.5s + 1.0s ≈ 1.5s worst case) keeps SSE latency acceptable while riding out brief overload spikes.

- [ ] **Step 1: Write the failing test**

Create `tutor/test_stream_retry.py`. It fakes `anthropic.Anthropic` so `messages.stream(...)` raises `InternalServerError` on the first call and succeeds on the second, and patches `time.sleep` so the test is instant. It reuses the `_FakeStream` shape from `tutor/test_run_tutor_json_mode.py`.

```python
"""Regression: the raw Anthropic tutor stream retries transient errors before
any visible delta, then succeeds. Covers the toym26 incident (a single overloaded
529 killed the turn with no retry).

Run:
    python -m tutor.test_stream_retry
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest import mock

import anthropic

import tutor.run_tutor as rt


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    @property
    def text_stream(self):
        return iter(self._chunks)

    def get_final_message(self):
        return SimpleNamespace(content=[], usage=None, model="claude-sonnet-5")


def _make_overloaded_error():
    # InternalServerError needs a response + body; construct via a minimal httpx response.
    import httpx
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(529, request=req)
    return anthropic.InternalServerError("Overloaded", response=resp, body=None)


class _FlakyClient:
    """First stream() call raises; second returns a good stream."""

    def __init__(self):
        self.calls = 0
        self.messages = self

    def stream(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise _make_overloaded_error()
        return _FakeStream(['{"pedagogical-reasoning":"r","Student-facing-answer":"ok now"}'])


def test_retries_transient_error_then_succeeds():
    client = _FlakyClient()
    with mock.patch.object(rt.anthropic, "Anthropic", return_value=client), \
         mock.patch.dict("os.environ", {"TUTOR_JSON_MODE": "off"}), \
         mock.patch.object(rt.time, "sleep") as sleep:
        plan = [("system_static", "SYS"), ("student", "help")]
        out = list(rt.stream_tutor_reply_anthropic_raw(
            plan, model_name="claude-sonnet-5", api_key="k"))

    assert client.calls == 2, f"expected 1 retry (2 calls), got {client.calls}"
    assert sleep.called, "expected a backoff sleep between attempts"
    visible = "".join(x for x in out if isinstance(x, str))
    assert visible == "ok now", visible
    done = out[-1]
    assert done[0] == "__done__"
    assert json.loads(done[1])["Student-facing-answer"] == "ok now"


def test_gives_up_after_max_retries_and_reraises():
    class _AlwaysFails:
        def __init__(self):
            self.calls = 0
            self.messages = self

        def stream(self, **kwargs):
            self.calls += 1
            raise _make_overloaded_error()

    client = _AlwaysFails()
    with mock.patch.object(rt.anthropic, "Anthropic", return_value=client), \
         mock.patch.dict("os.environ", {"TUTOR_JSON_MODE": "off"}), \
         mock.patch.object(rt.time, "sleep"):
        plan = [("system_static", "SYS"), ("student", "help")]
        raised = False
        try:
            list(rt.stream_tutor_reply_anthropic_raw(
                plan, model_name="claude-sonnet-5", api_key="k"))
        except anthropic.InternalServerError:
            raised = True
    # 1 initial + _MAX_STREAM_RETRIES attempts, then re-raise.
    assert client.calls == rt._MAX_STREAM_RETRIES + 1, client.calls
    assert raised, "expected the last transient error to propagate"


if __name__ == "__main__":
    test_retries_transient_error_then_succeeds()
    test_gives_up_after_max_retries_and_reraises()
    print("PASS - transient stream errors retry then succeed / give up")
```

> If constructing `InternalServerError` via `httpx.Response` proves fiddly under 0.105.2, substitute `anthropic.APIConnectionError(message="boom", request=req)` (connection errors take only `request=`) in `_make_overloaded_error` — it is in the same `_RETRYABLE_ANTHROPIC_ERRORS` tuple and exercises the identical retry path.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m tutor.test_stream_retry`
Expected: FAIL — the first `stream()` call's exception propagates on attempt 1 (`client.calls == 1`), and `rt.time` / `rt._MAX_STREAM_RETRIES` don't exist yet (`AttributeError`).

- [ ] **Step 3: Add `import time` and retry constants**

Add `import time` alongside the stdlib imports in [run_tutor.py](../../../tutor/run_tutor.py#L10-L15) (after `import re`):

```python
import re
import time
```

Near the existing `_MAX_MSG_BREAKPOINTS = 3` / `_CACHE_EVERY = 15` constants (~[run_tutor.py:893](../../../tutor/run_tutor.py#L893)), add:

```python
# Transient Anthropic failures worth retrying BEFORE the first visible delta:
# rate limits (429), overloaded / 5xx (InternalServerError, incl. 529), and
# connection-level blips. Retried only pre-stream — see stream_tutor_reply_anthropic_raw.
_RETRYABLE_ANTHROPIC_ERRORS = (
    anthropic.RateLimitError,
    anthropic.InternalServerError,
    anthropic.APITimeoutError,
    anthropic.APIConnectionError,
)
_MAX_STREAM_RETRIES = 2
_RETRY_BASE_DELAY = 0.5  # seconds; exponential: 0.5s, then 1.0s


def _retry_backoff_seconds(attempt: int) -> float:
    """Backoff before retry ``attempt`` (1-indexed): 0.5s, 1.0s, ..."""
    return _RETRY_BASE_DELAY * (2 ** (attempt - 1))
```

- [ ] **Step 4: Wrap the streaming body in the retry loop**

Replace the body of `stream_tutor_reply_anthropic_raw` from the `extractor = StudentAnswerExtractor()` line through `final_message = stream.get_final_message()` ([run_tutor.py:1039-1065](../../../tutor/run_tutor.py#L1039-L1065)) with a retry loop. The setup (`build_anthropic_request`, `client`, `enforce`, `stream_kwargs`) stays above it; the recovery/`__done__` tail ([run_tutor.py:1067-1080](../../../tutor/run_tutor.py#L1067-L1080)) stays below, unchanged, reading `extractor` and `final_message` from the loop.

```python
    system_blocks, messages = build_anthropic_request(
        plan, images=images, images_by_student=images_by_student
    )
    client = anthropic.Anthropic(api_key=api_key)
    enforce = json_mode_enabled()
    stream_kwargs = dict(
        model=model_name, max_tokens=8192, system=system_blocks, messages=messages,
        thinking={"type": "disabled"},
    )
    if enforce:
        stream_kwargs.update(anthropic_tool_kwargs())

    extractor = None
    final_message = None
    attempt = 0
    while True:
        # Fresh extractor per attempt so a partially-fed buffer never leaks across retries.
        extractor = StudentAnswerExtractor()
        final_message = None
        yielded_any = False
        try:
            with client.messages.stream(**stream_kwargs) as stream:
                if enforce:
                    for event in stream:
                        if getattr(event, "type", None) == "input_json":
                            visible = extractor.feed(event.partial_json)
                            if visible:
                                yielded_any = True
                                yield visible
                else:
                    for text in stream.text_stream:
                        visible = extractor.feed(text)
                        if visible:
                            yielded_any = True
                            yield visible
                final_message = stream.get_final_message()
            break  # streamed cleanly
        except _RETRYABLE_ANTHROPIC_ERRORS:
            # Only safe to retry before any bytes reached the client, and only
            # up to the bounded cap; otherwise let it propagate (chat.py logs it
            # and emits the SSE error frame).
            if yielded_any or attempt >= _MAX_STREAM_RETRIES:
                raise
            attempt += 1
            time.sleep(_retry_backoff_seconds(attempt))
```

- [ ] **Step 5: Run the new test to verify it passes**

Run: `python -m tutor.test_stream_retry`
Expected: `PASS - transient stream errors retry then succeed / give up`

- [ ] **Step 6: Run the existing raw-stream tests to confirm no regression**

Run: `python -m tutor.test_stream_thinking_disabled` and `python -m pytest tutor/test_run_tutor_json_mode.py -q`
Expected: both PASS — the retry loop preserves the `thinking` kwarg, tool-forcing, and extractor recovery behavior these cover.

- [ ] **Step 7: Commit**

```bash
git add tutor/run_tutor.py tutor/test_stream_retry.py
git commit -m "fix(tutor): retry transient Anthropic stream errors with bounded backoff"
```

---

## Task 3: Preserve the student message and offer Retry on failure (frontend)

Stop the destructive rollback. On a stream error: keep the student bubble, do **not** silently refill the composer, show a reason-specific message, and add an explicit **Retry** button that re-sends that exact turn (text + attachments). Ship it with a cache-buster so browsers actually pick up the new JS.

**Files:**
- Modify: `ui_core/templates/base_chat.html` — add a Retry button to the error banner ([base_chat.html:58-61](../../../ui_core/templates/base_chat.html#L58-L61)).
- Modify: `main_ui/templates/embed.html` — override the `chat_js_src` block to cache-bust main_ui's chat.js ([embed.html:1](../../../main_ui/templates/embed.html#L1)).
- Modify: `main_ui/static/js/chat.js` — grab the new button ([chat.js:44-45](../../../main_ui/static/js/chat.js#L44-L45) area); add `friendlyStreamError()` and update `showError()`/`hideError()` ([chat.js:396-404](../../../main_ui/static/js/chat.js#L396-L404)); rewrite the `if (streamError)` block ([chat.js:1140-1147](../../../main_ui/static/js/chat.js#L1140-L1147)).
- Test: none automated — no JS test harness exists in this repo. Manual verification via the local QA server (Step 6).

**Interfaces:**
- Consumes: existing `sendMessage()`, module-scoped `stagedImages` / `stagedFiles` (reassignable `let`), `renderStagedPreviews()`, `composerInput`, `hideError()`, and the closure locals `originalText`, `outgoingImages`, `outgoingFiles`, `studentBubble`, `tutorBubble`, `revokeOutgoing` (all in scope at the `if (streamError)` block).
- Produces: `friendlyStreamError(reason: string) -> string`; `showError(reason, onRetry?)` where an optional `onRetry` callback wires the Retry button; a new DOM element `#error-retry`.

**Design notes:**
- The sandbox app cache-busts chat.js with `?v=` and there's a memory note about bumping it. main_ui currently ships chat.js with **no** version param (it uses the default `chat_js_src` block). Add an override so this change reliably reaches students; start at `v='1'` and bump on future edits.
- Retry restores `composerInput.value = originalText`, re-stages the captured `outgoingImages`/`outgoingFiles`, removes the failed bubbles, then calls `sendMessage()` — reusing all existing send logic rather than duplicating it. Do **not** call `revokeOutgoing()` before a retry (the object URLs are re-used by the re-render); only revoke if the user dismisses instead.

- [ ] **Step 1: Add the Retry button to the error banner**

In [base_chat.html:58-61](../../../ui_core/templates/base_chat.html#L58-L61), add a Retry button between the text span and the dismiss button:

```html
        <div class="error-banner" id="error-banner" role="alert" hidden>
            <span class="error-text" id="error-text"></span>
            <button class="error-retry" id="error-retry" type="button" hidden>Retry</button>
            <button class="error-dismiss" id="error-dismiss" type="button" aria-label="Dismiss error">&times;</button>
        </div>
```

- [ ] **Step 2: Cache-bust main_ui's chat.js**

In [main_ui/templates/embed.html](../../../main_ui/templates/embed.html#L1), add a `chat_js_src` block override below the `extends` line (mirrors `sandbox_ui/templates/embed.html:68`):

```html
{% extends "base_chat.html" %}
{% block chat_js_src %}{{ url_for('static', filename='js/chat.js', v='1') }}{% endblock %}
```

- [ ] **Step 3: Grab the new button element**

In [chat.js](../../../main_ui/static/js/chat.js#L44-L45), next to the existing `errorBanner` / `errorText` lookups, add:

```javascript
  const errorRetry = document.getElementById("error-retry");
```

- [ ] **Step 4: Add `friendlyStreamError` and wire Retry into `showError`/`hideError`**

Replace `showError` / `hideError` ([chat.js:396-404](../../../main_ui/static/js/chat.js#L396-L404)) with:

```javascript
  function friendlyStreamError(reason) {
    const r = String(reason || "");
    if (/RateLimitError|429|InternalServerError|529|overloaded/i.test(r)) {
      return "The tutor is busy right now. Give it a moment, then press Retry.";
    }
    if (/APITimeoutError|APIConnectionError|timeout|Connection error/i.test(r)) {
      return "Couldn't reach the tutor. Check your connection, then press Retry.";
    }
    return "Something went wrong. Press Retry to try again.";
  }

  function showError(reason, onRetry) {
    errorText.textContent = reason;
    if (errorRetry) {
      if (onRetry) {
        errorRetry.hidden = false;
        errorRetry.onclick = () => {
          hideError();
          onRetry();
        };
      } else {
        errorRetry.hidden = true;
        errorRetry.onclick = null;
      }
    }
    errorBanner.hidden = false;
  }

  function hideError() {
    errorBanner.hidden = true;
    errorText.textContent = "";
    if (errorRetry) {
      errorRetry.hidden = true;
      errorRetry.onclick = null;
    }
  }
```

> All existing `showError("...")` calls keep working (the `onRetry` arg is optional and defaults to no Retry button).

- [ ] **Step 5: Rewrite the `if (streamError)` rollback block**

Replace the `if (streamError) { ... }` block at [chat.js:1140-1147](../../../main_ui/static/js/chat.js#L1140-L1147) with a non-destructive version that keeps the student bubble and offers Retry:

```javascript
      if (streamError) {
        // Keep the student bubble so the message stays visible — deleting it and
        // silently restoring the composer text (old behavior) caused blind resends.
        // Replace only the tutor placeholder with a reason-specific banner + Retry
        // that re-sends this exact turn (text + attachments).
        tutorBubble.remove();
        const retry = () => {
          studentBubble.remove();
          composerInput.value = originalText;
          stagedImages = outgoingImages.slice();
          stagedFiles = outgoingFiles.slice();
          renderStagedPreviews();
          sendMessage();
        };
        showError(friendlyStreamError(streamError), retry);
        return;
      }
```

- [ ] **Step 6: Manual verification (local QA server)**

There is no JS test runner. Verify by hand against a local instance (see the local-QA-server memory note for env-prefix / TaskStop gotchas):

1. Start main_ui locally and open the chat page.
2. Force a stream error. Two options:
   - Temporarily edit [chat.py:363-367](../../../main_ui/routes/chat.py#L363-L367) area to `raise anthropic.InternalServerError(...)` at stream start, **or**
   - In DevTools, block the `/api/chat` request (Network → block request URL) to trigger the frontend error path.
3. Confirm: the **student bubble stays**, the composer is **not** silently refilled, the banner reads *"The tutor is busy right now…"* (or the connection variant), and a **Retry** button appears.
4. Click **Retry**: the failed bubbles are removed, the message (and any attachments) re-sends, and on success the tutor reply renders normally.
5. Revert any temporary server edit from step 2.

- [ ] **Step 7: Commit**

```bash
git add ui_core/templates/base_chat.html main_ui/templates/embed.html main_ui/static/js/chat.js
git commit -m "fix(chat_ui): keep student message and offer retry on stream error"
```

---

## Self-Review

**Spec coverage:**
- Fix 1 (log the swallowed exception) → Task 1. ✓
- Fix 2 (retry 429/529/timeout/connection with backoff, only before first delta, reset extractor) → Task 2. ✓
- Fix 3 (keep the student bubble, inline Retry instead of delete+restore, surface rate-limit specifically) → Task 3. ✓
- Ship reliability (main_ui chat.js had no cache-buster) → Task 3, Step 2. ✓

**Placeholder scan:** No TBD/TODO/"handle edge cases". Every code step carries real code. The two "verify names against neighbor file" notes are pointers to confirm imports, not deferred work — the test intent and impl code are fully specified.

**Type consistency:**
- `_RETRYABLE_ANTHROPIC_ERRORS`, `_MAX_STREAM_RETRIES`, `_RETRY_BASE_DELAY`, `_retry_backoff_seconds` — defined in Task 2 Step 3, used in Step 4 and asserted in Step 1's test (`rt._MAX_STREAM_RETRIES`, `rt.time`). ✓
- `friendlyStreamError` / `showError(reason, onRetry)` / `#error-retry` — defined in Task 3 Step 1/3/4, consumed in Step 5. ✓
- Task 2's retry loop leaves `extractor` and `final_message` bound for the unchanged recovery tail (`extractor.buffer`, `extractor.found_answer`, `_tool_input_from_message(final_message)`). ✓

**Independence / deploy order:** Task 1 (log-only, no client change) → Task 2 (server retry; Task 1's log confirms retries in prod) → Task 3 (frontend + cache-bust). No task imports another's code; each is independently revertible.
