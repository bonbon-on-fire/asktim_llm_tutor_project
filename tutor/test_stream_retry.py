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


# --- Tool-forcing (enforce) branch fakes, mirroring test_run_tutor_json_mode.py ---

class _FakeToolStream:
    """Mimics anthropic MessageStream for the tool-forcing (input_json event) path."""

    def __init__(self, events, final):
        self._events = events
        self._final = final

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def __iter__(self):
        return iter(self._events)

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


class _FlakyToolClient:
    """First stream() call raises; second returns a good tool-forcing (input_json) stream."""

    def __init__(self, events, final):
        self.calls = 0
        self.messages = self
        self._events = events
        self._final = final

    def stream(self, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise _make_overloaded_error()
        return _FakeToolStream(self._events, self._final)


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


def test_retries_transient_error_then_succeeds_on_tool_forcing_path():
    """json_mode_enabled() defaults to True (TUTOR_JSON_MODE unset/"1"), so the
    tool-forcing (enforce) branch — iterating input_json events — is the DEFAULT
    production path, and the actual incident's stream. Cover retry there too."""
    reasoning = "hidden plan"
    answer = "Try isolating x first."
    full = json.dumps({"pedagogical-reasoning": reasoning, "Student-facing-answer": answer})
    frags = [full[i:i + 7] for i in range(0, len(full), 7)]
    client = _FlakyToolClient(_input_json_events(frags), _final_with_tool(reasoning, answer))
    with mock.patch.object(rt.anthropic, "Anthropic", return_value=client), \
         mock.patch.dict("os.environ", {"TUTOR_JSON_MODE": "1"}), \
         mock.patch.object(rt.time, "sleep") as sleep:
        plan = [("system_static", "SYS"), ("student", "help")]
        out = list(rt.stream_tutor_reply_anthropic_raw(
            plan, model_name="claude-sonnet-5", api_key="k"))

    assert client.calls == 2, f"expected 1 retry (2 calls), got {client.calls}"
    assert sleep.called, "expected a backoff sleep between attempts"
    visible = "".join(x for x in out if isinstance(x, str))
    assert visible == answer, visible
    done = out[-1]
    assert done[0] == "__done__"
    parsed = json.loads(done[1])
    assert parsed["Student-facing-answer"] == answer
    assert parsed["pedagogical-reasoning"] == reasoning


if __name__ == "__main__":
    test_retries_transient_error_then_succeeds()
    test_gives_up_after_max_retries_and_reraises()
    test_retries_transient_error_then_succeeds_on_tool_forcing_path()
    print("PASS - transient stream errors retry then succeed / give up")
