# JSON Mode Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enforce well-formed two-field JSON (`pedagogical-reasoning`, `Student-facing-answer`) on every live tutor output path via API-level structured output, removing the pedagogical-reasoning leak and malformed-LaTeX-JSON failures by construction.

**Architecture:** A single contract module (`tutor/json_mode.py`) owns the schema and an env gate (`TUTOR_JSON_MODE`, default ON). Anthropic enforcement = tool-forcing (answer arrives as a forced `tutor_reply` tool call); OpenAI enforcement = native `response_format` json_schema (still streams as content text). The existing `StudentAnswerExtractor` is unchanged — it already walks the `{"pedagogical-reasoning":…,"Student-facing-answer":…}` shape, so we only change the *source* of the fragments it is fed (tool-input deltas for Claude). Recovery is authoritative from the structured dict; the best-effort parse/repair layer is retained as the gate-off fallback.

**Tech Stack:** Python, anthropic 0.105.2 (raw SDK streaming), langchain-anthropic 1.4.4, langchain-openai 1.2.2, langchain-core 1.4.0, pytest.

## Global Constraints

- Conventional-commit messages, `type(scope): subject`. **Do NOT** add a `Co-Authored-By: Claude` trailer (repo rule).
- Gate semantics mirror `cached_history_enabled()` exactly: env value in `{"0","false","no","off"}` (case-insensitive, stripped) → OFF; anything else incl. unset → ON.
- Schema is exactly two required string fields: `pedagogical-reasoning`, `Student-facing-answer`, `additionalProperties: false`.
- Gate OFF must be byte-identical to today's behavior on every path (no tools in request, no `response_format`).
- The tutor tool name is `tutor_reply` everywhere.
- Do not change the tutor prompt content, the SSE delta contract, or the two-field schema.
- `thinking={"type":"disabled"}` stays on the Claude raw stream (forced tool_choice is incompatible with extended thinking).

---

### Task 1: Contract module + gate (`tutor/json_mode.py`)

**Files:**
- Create: `tutor/json_mode.py`
- Test: `tutor/test_json_mode.py`

**Interfaces:**
- Produces:
  - `TUTOR_TOOL_NAME: str` = `"tutor_reply"`
  - `json_mode_enabled() -> bool`
  - `anthropic_tool_kwargs() -> dict` → `{"tools": [ {"name","description","input_schema"} ], "tool_choice": {"type":"tool","name":"tutor_reply"}}`
  - `anthropic_tools() -> list` → just the `tools` list (for langchain `bind_tools`)
  - `openai_response_format() -> dict` → `{"type":"json_schema","json_schema":{"name":"tutor_reply","schema":{...},"strict":True}}`

- [ ] **Step 1: Write the failing test**

```python
# tutor/test_json_mode.py
from tutor import json_mode as jm


def test_gate_defaults_on_and_falsey_off(monkeypatch):
    monkeypatch.delenv("TUTOR_JSON_MODE", raising=False)
    assert jm.json_mode_enabled() is True
    for off in ("0", "false", "no", "off", "OFF", " Off "):
        monkeypatch.setenv("TUTOR_JSON_MODE", off)
        assert jm.json_mode_enabled() is False
    monkeypatch.setenv("TUTOR_JSON_MODE", "1")
    assert jm.json_mode_enabled() is True


def test_anthropic_tool_kwargs_shape():
    kw = jm.anthropic_tool_kwargs()
    assert kw["tool_choice"] == {"type": "tool", "name": "tutor_reply"}
    tool = kw["tools"][0]
    assert tool["name"] == "tutor_reply"
    props = tool["input_schema"]["properties"]
    assert set(props) == {"pedagogical-reasoning", "Student-facing-answer"}
    assert tool["input_schema"]["additionalProperties"] is False
    assert set(tool["input_schema"]["required"]) == {"pedagogical-reasoning", "Student-facing-answer"}


def test_openai_response_format_shape():
    rf = jm.openai_response_format()
    assert rf["type"] == "json_schema"
    js = rf["json_schema"]
    assert js["name"] == "tutor_reply"
    assert js["strict"] is True
    assert set(js["schema"]["properties"]) == {"pedagogical-reasoning", "Student-facing-answer"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tutor/test_json_mode.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tutor.json_mode'`.

- [ ] **Step 3: Write minimal implementation**

```python
# tutor/json_mode.py
"""Structured-output enforcement for tutor replies.

The tutor must return a two-field JSON object (``pedagogical-reasoning`` and
``Student-facing-answer``). Rather than trust the model to hand-serialize valid
JSON, we enforce it at the API layer: tool-forcing on Anthropic, native
``response_format`` on OpenAI. This module is the single owner of that contract so
every code path (raw SDK, langchain streaming, langchain invoke) reads the same
schema and the same on/off gate.
"""
from __future__ import annotations

import os

TUTOR_TOOL_NAME = "tutor_reply"

_TUTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "pedagogical-reasoning": {
            "type": "string",
            "description": "Hidden tutor-only reasoning; never shown to the student.",
        },
        "Student-facing-answer": {
            "type": "string",
            "description": "The reply shown to the student.",
        },
    },
    "required": ["pedagogical-reasoning", "Student-facing-answer"],
    "additionalProperties": False,
}

_JSON_MODE_FALSEY = {"0", "false", "no", "off"}


def json_mode_enabled() -> bool:
    """Enforced structured output is the DEFAULT tutor path.

    Set ``TUTOR_JSON_MODE`` to ``0``/``false``/``no``/``off`` to fall back to the
    legacy best-effort parse/repair path (instant rollback). Any other value — or
    leaving it unset — keeps enforcement on. Mirrors ``cached_history_enabled``.
    """
    return os.environ.get("TUTOR_JSON_MODE", "").strip().lower() not in _JSON_MODE_FALSEY


def anthropic_tools() -> list:
    """The single forced tutor tool, in Anthropic tool format (raw SDK + langchain)."""
    return [
        {
            "name": TUTOR_TOOL_NAME,
            "description": "Return the tutor reply as two fields.",
            "input_schema": _TUTOR_SCHEMA,
        }
    ]


def anthropic_tool_kwargs() -> dict:
    """Raw-SDK kwargs that force a single ``tutor_reply`` tool call."""
    return {
        "tools": anthropic_tools(),
        "tool_choice": {"type": "tool", "name": TUTOR_TOOL_NAME},
    }


def openai_response_format() -> dict:
    """langchain ChatOpenAI ``response_format`` for strict JSON-schema output."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": TUTOR_TOOL_NAME,
            "schema": _TUTOR_SCHEMA,
            "strict": True,
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tutor/test_json_mode.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add tutor/json_mode.py tutor/test_json_mode.py
git commit -m "feat(tutor): add json_mode contract module and TUTOR_JSON_MODE gate"
```

---

### Task 2: Claude raw-SDK streaming — tool-forcing (PRODUCTION path)

**Files:**
- Modify: `tutor/run_tutor.py` (`stream_tutor_reply_anthropic_raw`, add `_tool_input_from_message` helper, add import)
- Test: `tutor/test_run_tutor_json_mode.py`

**Interfaces:**
- Consumes: `tutor.json_mode.json_mode_enabled`, `anthropic_tool_kwargs`, `TUTOR_TOOL_NAME`.
- Produces: unchanged yield contract of `stream_tutor_reply_anthropic_raw` — visible `str` chunks, then `("__done__", normalized_json, usage_msg)`.
- New module-private helper `_tool_input_from_message(message) -> dict | None`.

Background: with `anthropic 0.105.2`, iterating `with client.messages.stream(...) as stream:` via `for event in stream:` yields high-level events. Tool input deltas are `event.type == "input_json"` with `event.partial_json` (the delta str). `stream.get_final_message()` returns the terminal `Message`; its `tool_use` content block exposes `.input` as a real dict. Under tool-forcing there is **no** text content, so `stream.text_stream` would be empty — we must iterate events instead.

- [ ] **Step 1: Write the failing test**

```python
# tutor/test_run_tutor_json_mode.py
import json
from types import SimpleNamespace
from unittest.mock import patch

import tutor.run_tutor as rt


class _FakeStream:
    """Mimics anthropic MessageStream: event iteration + get_final_message()."""
    def __init__(self, events, final):
        self._events = events
        self._final = final
    def __enter__(self):
        return self
    def __exit__(self, *a):
        return False
    def __iter__(self):
        return iter(self._events)
    @property
    def text_stream(self):
        return iter([e.text for e in self._events if getattr(e, "type", None) == "text"])
    def get_final_message(self):
        return self._final


def _input_json_events(fragments):
    return [SimpleNamespace(type="input_json", partial_json=f) for f in fragments]


def _final_with_tool(reasoning, answer):
    block = SimpleNamespace(
        type="tool_use",
        name="tutor_reply",
        input={"pedagogical-reasoning": reasoning, "Student-facing-answer": answer},
    )
    return SimpleNamespace(content=[block], usage=None, model="claude-sonnet-5")


class _FakeClient:
    def __init__(self, stream):
        self._stream = stream
        self.messages = self
    def stream(self, **kwargs):
        _FakeClient.captured = kwargs
        return self._stream


def test_raw_stream_tool_forcing_streams_answer_and_recovers_reasoning(monkeypatch):
    monkeypatch.setenv("TUTOR_JSON_MODE", "1")
    # The tool input JSON serialized in fragments; reasoning first, then answer.
    full = json.dumps({"pedagogical-reasoning": "hidden plan",
                       "Student-facing-answer": "Try isolating x first."})
    frags = [full[i:i + 7] for i in range(0, len(full), 7)]
    stream = _FakeStream(_input_json_events(frags), _final_with_tool("hidden plan", "Try isolating x first."))
    with patch.object(rt.anthropic, "Anthropic", return_value=_FakeClient(stream)):
        out = list(rt.stream_tutor_reply_anthropic_raw(
            [("system_static", "SYS"), ("student", "help")],
            model_name="claude-sonnet-5", api_key="k"))
    # Request carried the forced tool.
    assert _FakeClient.captured["tool_choice"] == {"type": "tool", "name": "tutor_reply"}
    assert _FakeClient.captured["tools"][0]["name"] == "tutor_reply"
    # Visible stream reconstructs the student answer only (no reasoning leak).
    visible = "".join(x for x in out if isinstance(x, str))
    assert visible == "Try isolating x first."
    done = out[-1]
    assert done[0] == "__done__"
    parsed = json.loads(done[1])
    assert parsed["Student-facing-answer"] == "Try isolating x first."
    assert parsed["pedagogical-reasoning"] == "hidden plan"


def test_raw_stream_gate_off_uses_text_stream_no_tools(monkeypatch):
    monkeypatch.setenv("TUTOR_JSON_MODE", "off")
    full = json.dumps({"pedagogical-reasoning": "r", "Student-facing-answer": "hello"})
    text_events = [SimpleNamespace(type="text", text=full)]
    stream = _FakeStream(text_events, SimpleNamespace(content=[], usage=None, model="claude-sonnet-5"))
    with patch.object(rt.anthropic, "Anthropic", return_value=_FakeClient(stream)):
        out = list(rt.stream_tutor_reply_anthropic_raw(
            [("system_static", "SYS"), ("student", "hi")],
            model_name="claude-sonnet-5", api_key="k"))
    assert "tools" not in _FakeClient.captured
    assert "tool_choice" not in _FakeClient.captured
    visible = "".join(x for x in out if isinstance(x, str))
    assert visible == "hello"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tutor/test_run_tutor_json_mode.py -v`
Expected: FAIL — the current function always uses `stream.text_stream` and never sends tools, so `test_raw_stream_tool_forcing...` fails on the `tool_choice` assertion / empty visible stream.

- [ ] **Step 3: Write minimal implementation**

Add the import near the other `tutor` imports at the top of `tutor/run_tutor.py`:

```python
from tutor.json_mode import (
    TUTOR_TOOL_NAME,
    anthropic_tool_kwargs,
    json_mode_enabled,
)
```

Add this helper just above `stream_tutor_reply_anthropic_raw`:

```python
def _tool_input_from_message(message) -> dict | None:
    """Return the forced ``tutor_reply`` tool call's ``input`` dict, or None.

    The raw-SDK final ``Message`` carries content blocks; under tool-forcing the
    answer lives in the ``tool_use`` block's already-parsed ``input`` (guaranteed
    valid JSON — no repair needed)."""
    for block in getattr(message, "content", None) or []:
        if getattr(block, "type", None) == "tool_use" and getattr(block, "name", None) == TUTOR_TOOL_NAME:
            inp = getattr(block, "input", None)
            if isinstance(inp, dict):
                return inp
    return None
```

Replace the body of `stream_tutor_reply_anthropic_raw` (currently lines ~969-997) from the `client = anthropic.Anthropic(...)` line through the final `yield` with:

```python
    client = anthropic.Anthropic(api_key=api_key)
    extractor = StudentAnswerExtractor()
    final_message = None
    enforce = json_mode_enabled()
    stream_kwargs = dict(
        model=model_name, max_tokens=8192, system=system_blocks, messages=messages,
        # Disable extended thinking (mirrors build_tutor_model). Sonnet 5's default
        # is adaptive thinking; left on it streams thinking blocks separately and can
        # burn the whole max_tokens budget before the answer is emitted.
        thinking={"type": "disabled"},
    )
    if enforce:
        # Force a single tutor_reply tool call: the answer arrives as the tool's
        # input (guaranteed-valid JSON), streamed as input_json deltas.
        stream_kwargs.update(anthropic_tool_kwargs())
    with client.messages.stream(**stream_kwargs) as stream:
        if enforce:
            for event in stream:
                if getattr(event, "type", None) == "input_json":
                    visible = extractor.feed(event.partial_json)
                    if visible:
                        yield visible
        else:
            for text in stream.text_stream:
                visible = extractor.feed(text)
                if visible:
                    yield visible
        final_message = stream.get_final_message()

    # Recovery: enforced -> authoritative tool_use.input dict (no repair). Otherwise
    # the accumulated free-text buffer, run through the best-effort normalizer.
    raw = extractor.buffer
    if enforce:
        tool_input = _tool_input_from_message(final_message)
        if tool_input is not None:
            raw = json.dumps(tool_input, ensure_ascii=False)
    normalized = _normalize_tutor_ai_message(AIMessage(content=raw))
    normalized_text = normalized.content if isinstance(normalized.content, str) else str(normalized.content)
    if not extractor.found_answer:
        _, answer = parse_tutor_response(normalized_text)
        if answer:
            yield answer
    yield ("__done__", normalized_text, _anthropic_usage_message(final_message))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tutor/test_run_tutor_json_mode.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Run the existing raw-path and cached-history suites for regressions**

Run: `python -m pytest tutor/test_cached_history.py tutor/test_run_tutor.py -q`
Expected: PASS (no regressions; gate-off path unchanged).

- [ ] **Step 6: Commit**

```bash
git add tutor/run_tutor.py tutor/test_run_tutor_json_mode.py
git commit -m "feat(tutor): force tutor_reply tool call on the Claude raw streaming path"
```

---

### Task 3: langchain enforcement helper + legacy Claude streaming

**Files:**
- Modify: `tutor/run_tutor.py` (add `_apply_json_mode`, `_chunk_json_fragment`; use them in `stream_tutor_reply`)
- Test: `tutor/test_run_tutor_json_mode.py` (extend)

**Interfaces:**
- Consumes: `tutor.json_mode.anthropic_tools`, `openai_response_format`, `json_mode_enabled`, `TUTOR_TOOL_NAME`.
- Produces:
  - `_apply_json_mode(model) -> model` — returns a bound model (Claude → `bind_tools(..., tool_choice="tutor_reply")`; OpenAI → `bind(response_format=…)`) when the gate is on, else the model unchanged. Applied only at `.stream()`/`.invoke()` call sites so the *cached* model stays a plain instance and the `isinstance(model, ChatAnthropic)` checks in `_build_system_message`/`_cache_last_message` keep working.
  - `_chunk_json_fragment(chunk) -> str` — the JSON text fragment from a langchain `AIMessageChunk`: its `.content` when non-empty (OpenAI/text), else the concatenated `.tool_call_chunks` args (Claude tool-forced).

- [ ] **Step 1: Write the failing test**

```python
# append to tutor/test_run_tutor_json_mode.py
from langchain_core.messages import AIMessageChunk


def test_chunk_json_fragment_prefers_content_then_tool_args():
    # OpenAI/text path: content carries the JSON.
    assert rt._chunk_json_fragment(AIMessageChunk(content='{"a":1}')) == '{"a":1}'
    # Claude tool-forced path: content empty, args carry the JSON fragment.
    tc = AIMessageChunk(
        content="",
        tool_call_chunks=[{"name": "tutor_reply", "args": '{"Student', "id": "1", "index": 0}],
    )
    assert rt._chunk_json_fragment(tc) == '{"Student'


def test_apply_json_mode_binds_per_provider(monkeypatch):
    monkeypatch.setenv("TUTOR_JSON_MODE", "1")
    claude = rt.build_tutor_model("claude")
    bound = rt._apply_json_mode(claude)
    assert bound is not claude  # a RunnableBinding wrapping the model
    # kwargs carry the forced tool.
    assert bound.kwargs.get("tool_choice") is not None
    # Gate off -> untouched.
    monkeypatch.setenv("TUTOR_JSON_MODE", "off")
    assert rt._apply_json_mode(claude) is claude
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tutor/test_run_tutor_json_mode.py -k "fragment or apply_json_mode" -v`
Expected: FAIL — `AttributeError: module 'tutor.run_tutor' has no attribute '_chunk_json_fragment'`.

- [ ] **Step 3: Write minimal implementation**

Extend the import from `tutor.json_mode`:

```python
from tutor.json_mode import (
    TUTOR_TOOL_NAME,
    anthropic_tool_kwargs,
    anthropic_tools,
    json_mode_enabled,
    openai_response_format,
)
```

Add both helpers (near the top of the "Streaming support" section, above `StudentAnswerExtractor`):

```python
def _apply_json_mode(model):
    """Bind API-level structured-output enforcement to *model* when the gate is on.

    Claude -> force the ``tutor_reply`` tool; OpenAI -> strict ``response_format``.
    Applied at the call site (not at model-build time) so the cached model stays a
    plain ``ChatAnthropic``/``ChatOpenAI`` — the prompt-cache helpers key off
    ``isinstance(model, ChatAnthropic)`` and must not see a ``RunnableBinding``.
    Gate off, or an unknown model type, returns *model* unchanged.
    """
    if not json_mode_enabled():
        return model
    if isinstance(model, ChatAnthropic):
        return model.bind_tools(anthropic_tools(), tool_choice=TUTOR_TOOL_NAME)
    if isinstance(model, ChatOpenAI):
        return model.bind(response_format=openai_response_format())
    return model


def _chunk_json_fragment(chunk) -> str:
    """Return the JSON text fragment carried by a langchain ``AIMessageChunk``.

    OpenAI (text / ``response_format``) puts it in ``.content``; a tool-forced
    Claude chunk leaves ``.content`` empty and streams the tool input via
    ``.tool_call_chunks`` args. Either way the fragment has the same
    ``{"pedagogical-reasoning":…,"Student-facing-answer":…}`` shape the extractor
    already walks."""
    piece = getattr(chunk, "content", "")
    if not isinstance(piece, str):
        piece = ""
    if piece:
        return piece
    parts: list[str] = []
    for tcc in getattr(chunk, "tool_call_chunks", None) or []:
        args = tcc.get("args") if isinstance(tcc, dict) else None
        if args:
            parts.append(args)
    return "".join(parts)
```

Now use them in `stream_tutor_reply` (the langchain streaming path). Replace the streaming loop (currently `for chunk in model.stream(safe_messages):` … building `piece`):

```python
    for chunk in _apply_json_mode(model).stream(safe_messages):
        full_chunk = chunk if full_chunk is None else full_chunk + chunk
        piece = _chunk_json_fragment(chunk)
        visible = extractor.feed(piece)
        if visible:
            yield visible
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tutor/test_run_tutor_json_mode.py -k "fragment or apply_json_mode" -v`
Expected: PASS.

- [ ] **Step 5: Run the langchain streaming suite for regressions**

Run: `python -m pytest tutor/test_run_tutor.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tutor/run_tutor.py tutor/test_run_tutor_json_mode.py
git commit -m "feat(tutor): enforce json mode on the langchain streaming path"
```

---

### Task 4: Non-streaming graph invoke — recover from tool calls

**Files:**
- Modify: `tutor/run_tutor.py` (`tutor_node` invoke call in `create_tutor_graph`; `_normalize_tutor_ai_message`)
- Test: `tutor/test_run_tutor_json_mode.py` (extend)

**Interfaces:**
- Consumes: `_apply_json_mode`.
- Produces: `_normalize_tutor_ai_message` now recovers content from `msg.tool_calls[0]["args"]` when the message has tool calls (Claude tool-forced invoke returns empty text + parsed `tool_calls`), preserving `usage_metadata`/`response_metadata` carry-over.

- [ ] **Step 1: Write the failing test**

```python
# append to tutor/test_run_tutor_json_mode.py
from langchain_core.messages import AIMessage


def test_normalize_recovers_from_tool_calls():
    msg = AIMessage(
        content="",
        tool_calls=[{
            "name": "tutor_reply",
            "args": {"pedagogical-reasoning": "plan", "Student-facing-answer": "Answer here."},
            "id": "t1",
        }],
    )
    out = rt._normalize_tutor_ai_message(msg)
    parsed = json.loads(out.content)
    assert parsed["Student-facing-answer"] == "Answer here."
    assert parsed["pedagogical-reasoning"] == "plan"


def test_normalize_plain_string_unchanged():
    msg = AIMessage(content=json.dumps({"pedagogical-reasoning": "r", "Student-facing-answer": "a"}))
    out = rt._normalize_tutor_ai_message(msg)
    assert json.loads(out.content)["Student-facing-answer"] == "a"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tutor/test_run_tutor_json_mode.py -k normalize -v`
Expected: FAIL — `test_normalize_recovers_from_tool_calls` fails: current `_normalize` reads only `.content` (empty), yielding the "could not generate a valid response" fallback.

- [ ] **Step 3: Write minimal implementation**

In `_normalize_tutor_ai_message`, replace the first line that computes `content`:

```python
def _normalize_tutor_ai_message(msg: BaseMessage) -> AIMessage:
    """..."""  # keep the existing docstring
    tool_calls = getattr(msg, "tool_calls", None)
    if tool_calls:
        args = tool_calls[0].get("args") if isinstance(tool_calls[0], dict) else None
        if isinstance(args, dict) and args:
            content = json.dumps(args, ensure_ascii=False)
        else:
            content = msg.content if isinstance(msg.content, str) else str(msg.content)
    else:
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
    reasoning, answer = parse_tutor_response(content)
    # ... rest of function unchanged ...
```

In `create_tutor_graph`'s `tutor_node`, wrap the invoke:

```python
        response = _apply_json_mode(model).invoke(messages)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tutor/test_run_tutor_json_mode.py -k normalize -v`
Expected: PASS.

- [ ] **Step 5: Run the run_tutor suite for regressions**

Run: `python -m pytest tutor/test_run_tutor.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tutor/run_tutor.py tutor/test_run_tutor_json_mode.py
git commit -m "feat(tutor): recover tutor json from forced tool call on the graph path"
```

---

### Task 5: GPT cached bridge loop uses the shared helpers

**Files:**
- Modify: `ui_core/tutor_bridge.py` (import `_apply_json_mode`, `_chunk_json_fragment`; use them in the gpt cached-history streaming loop, lines ~617-628)
- Test: `ui_core/test_cached_history_bridge.py` (extend)

**Interfaces:**
- Consumes: `tutor.run_tutor._apply_json_mode`, `tutor.run_tutor._chunk_json_fragment`.
- Produces: no signature change; the gpt cached path now binds `response_format` when the gate is on and reads fragments via the shared helper.

- [ ] **Step 1: Write the failing test**

```python
# append to ui_core/test_cached_history_bridge.py
from unittest.mock import patch


def test_cached_gpt_binds_response_format_when_json_mode_on(monkeypatch):
    monkeypatch.setenv("TUTOR_JSON_MODE", "1")
    bridge = TutorBridge()
    captured = {}

    class FakeChunk:
        content = '{"pedagogical-reasoning":"r","Student-facing-answer":"hi"}'
        tool_call_chunks = []

    class FakeBound:
        def stream(self, messages, **kw):
            return iter([FakeChunk()])

    class FakeModel:
        def bind(self, **kw):
            captured["response_format"] = kw.get("response_format")
            return FakeBound()

    with patch.object(bridge, "_get_or_build_stream_context", return_value=(FakeModel(), "SYS")), \
         patch.object(bridge, "retrieved_context",
                      return_value=type("RC", (), {"text": "", "records": [], "embedding_tokens": 0})()), \
         patch.object(bridge, "_enforce_rag_available"):
        list(bridge.stream_tutor_reply(
            course="c", exercise="1", tutor="tutor_07", history=[],
            new_student_message="hello", provider="gpt",
            history_mode="cached", cached_history=[]))
    assert captured["response_format"] is not None
    assert captured["response_format"]["json_schema"]["name"] == "tutor_reply"
```

Note: the existing `FakeModel` in the other bridge tests defines `stream` directly (no `bind`). `_apply_json_mode` only binds for real `ChatOpenAI`/`ChatAnthropic` instances, so a bare fake without those base classes is returned unchanged and keeps calling `.stream` — the existing tests stay green. This new test exercises the bind path explicitly.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest ui_core/test_cached_history_bridge.py -k response_format -v`
Expected: FAIL — the bridge does not call `_apply_json_mode`, so `captured["response_format"]` is never set (KeyError).

- [ ] **Step 3: Write minimal implementation**

Add to the run_tutor imports in `ui_core/tutor_bridge.py`:

```python
from tutor.run_tutor import (
    StudentAnswerExtractor,
    _apply_json_mode,
    _chunk_json_fragment,
    _normalize_tutor_ai_message,
    _require_anthropic_api_key,
    build_tutor_model,
    create_tutor_graph,
    load_system_prompt,
    parse_tutor_response,
    stream_tutor_reply_anthropic_raw,
)
```

Replace the gpt cached streaming loop:

```python
            else:  # gpt via langchain (accepts interleaved system messages)
                lc_messages = self._plan_to_langchain(plan, images_by_student=images_by_student)
                extractor = StudentAnswerExtractor()
                full_chunk = None
                for chunk in _apply_json_mode(model).stream(lc_messages):
                    full_chunk = chunk if full_chunk is None else full_chunk + chunk
                    visible = extractor.feed(_chunk_json_fragment(chunk))
                    if visible:
                        yield {"type": "delta", "text": visible}
                full_raw = _normalize_tutor_ai_message(AIMessage(content=extractor.buffer)).content
                full_msg = full_chunk  # carries usage_metadata when stream_usage=True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest ui_core/test_cached_history_bridge.py -v`
Expected: PASS (new test + all existing bridge tests).

- [ ] **Step 5: Commit**

```bash
git add ui_core/tutor_bridge.py ui_core/test_cached_history_bridge.py
git commit -m "feat(bridge): enforce json mode on the gpt cached streaming path"
```

---

### Task 6: LaTeX round-trip integration test + action-item close-out

**Files:**
- Test: `tutor/test_run_tutor_json_mode.py` (extend)
- Modify: `meeting_notes/2026-07-23.md` (leave line 61 checked; add a one-line pointer to the flag)

**Interfaces:**
- Consumes: everything above (end-to-end through the raw path).

- [ ] **Step 1: Write the failing test (LaTeX + newlines round-trip)**

```python
# append to tutor/test_run_tutor_json_mode.py
def test_latex_and_newlines_round_trip_through_extractor(monkeypatch):
    monkeypatch.setenv("TUTOR_JSON_MODE", "1")
    answer = "Use \\(\\frac{a}{b}\\).\n\n| x | y |\n|---|---|\n| 1 | 2 |"
    reasoning = "check the fraction reduction"
    full = json.dumps({"pedagogical-reasoning": reasoning, "Student-facing-answer": answer})
    frags = [full[i:i + 5] for i in range(0, len(full), 5)]
    stream = _FakeStream(_input_json_events(frags), _final_with_tool(reasoning, answer))
    with patch.object(rt.anthropic, "Anthropic", return_value=_FakeClient(stream)):
        out = list(rt.stream_tutor_reply_anthropic_raw(
            [("system_static", "SYS"), ("student", "help")],
            model_name="claude-sonnet-5", api_key="k"))
    visible = "".join(x for x in out if isinstance(x, str))
    # KaTeX delimiters survive; the markdown table keeps real newlines.
    assert "\\(\\frac{a}{b}\\)" in visible
    assert "| 1 | 2 |" in visible
    done = out[-1]
    assert json.loads(done[1])["Student-facing-answer"] == answer
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `python -m pytest tutor/test_run_tutor_json_mode.py -k latex -v`
Expected: PASS is acceptable here (Task 2's implementation should already satisfy it). If it FAILS, the extractor's escape handling for streamed valid JSON needs a fix in Task 2 — do not skip. This test is the guard that valid-JSON tool input decodes identically to the authoritative dict.

- [ ] **Step 3: Full suite regression check**

Run: `python -m pytest tutor/ ui_core/ -q`
Expected: PASS except the two known-pre-existing sandbox_ui failures documented earlier (`test_chat_custom_ignored`, `test_chat_rag_fail_closed`), which are environmental and unrelated. Confirm no *new* failures.

- [ ] **Step 4: Update the meeting note pointer**

In `meeting_notes/2026-07-23.md`, keep line 61 checked and append the rollback flag note inline so future readers know the switch exists:

```markdown
  - [x] Enforce JSON mode on LangChain so the output is always well-formed — covers the LaTeX formatting issues and pedagogical-reasoning leaks. (Enforced by default; `TUTOR_JSON_MODE=off` reverts to best-effort parsing.)
```

- [ ] **Step 5: Commit**

```bash
git add tutor/test_run_tutor_json_mode.py meeting_notes/2026-07-23.md
git commit -m "test(tutor): latex round-trip guard for enforced json mode; note rollback flag"
```

---

## Self-Review

**Spec coverage:**
- §1 gate + schema module → Task 1. ✓
- §2 Claude cached raw SDK tool-forcing → Task 2. ✓
- §3 gpt `response_format` + legacy claude tools + non-streaming → Tasks 3 (legacy claude streaming + helper), 4 (non-streaming invoke), 5 (gpt cached bridge loop). ✓
- §4 recovery (authoritative dict) → Tasks 2 (`_tool_input_from_message`), 4 (`_normalize` tool_calls). ✓
- §4 cost/caching preserved (usage unchanged, tools inside cached prefix) → no code change needed; validated by regression suites + the caching note. The turn-2 `cache_read == turn-1 cache_write` smoke test from the spec is a live-API check; documented as a manual verification, not automated (no API key in CI).
- Testing items 1-6 → covered across Tasks 1-6. ✓
- Rollout flag → Task 1 + Task 6 note. ✓

**Placeholder scan:** none — every step has concrete code or exact commands.

**Type consistency:** `_apply_json_mode`, `_chunk_json_fragment`, `_tool_input_from_message`, `json_mode_enabled`, `anthropic_tool_kwargs`, `anthropic_tools`, `openai_response_format`, `TUTOR_TOOL_NAME` used consistently across tasks and match their definitions. `stream_tutor_reply_anthropic_raw` yield contract unchanged.

**Note on the caching smoke test:** the spec calls for verifying prompt-cache hits still land with tools present. This requires a live Anthropic key and is out of scope for the pytest suite; run it manually against staging after Task 2 (send two turns, assert turn-2 `cache_read_input_tokens` ≈ turn-1 `cache_creation_input_tokens`).
