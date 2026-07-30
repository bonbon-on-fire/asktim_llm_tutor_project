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
