"""Regression test: the raw-Anthropic tutor stream disables extended thinking.

Root cause of the intermittent "I could not generate a valid response" fallback:
Claude Sonnet 5 (the default tutor model) runs *adaptive thinking* by default when
the ``thinking`` parameter is omitted. In the cached-history streaming path,
``stream_tutor_reply_anthropic_raw`` calls ``client.messages.stream(...)`` — if it
doesn't disable thinking, thinking blocks can consume the whole ``max_tokens``
budget before the visible Student-facing-answer is emitted, leaving the text stream
empty and triggering the fallback. The non-streaming ``build_tutor_model`` already
disables thinking for exactly this reason; this asserts the streaming path matches.

Run:
    python -m tutor.test_stream_thinking_disabled
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest import mock

from tutor.run_tutor import stream_tutor_reply_anthropic_raw


class _FakeStream:
    """Minimal stand-in for anthropic's streaming response object."""

    def __init__(self, chunks):
        self._chunks = chunks

    @property
    def text_stream(self):
        return iter(self._chunks)

    def get_final_message(self):
        # A real final message always carries .model; provide it so
        # _anthropic_usage_message doesn't touch its free `model_name`.
        return mock.Mock(usage=None, model="claude-sonnet-5")


def _run_and_capture_stream_kwargs() -> dict:
    """Drive the raw sender with a fake anthropic client; return the stream kwargs.

    Pinned to the legacy (gate-off) path: this test only cares about the
    ``thinking`` kwarg, which is unconditional in both branches, and the fake
    stream here only implements ``text_stream`` (not event iteration).
    """
    captured: dict = {}

    @contextmanager
    def fake_stream(**kwargs):
        captured.update(kwargs)
        yield _FakeStream(['{"pedagogical-reasoning":"r","Student-facing-answer":"ok"}'])

    fake_client = mock.Mock()
    fake_client.messages.stream.side_effect = fake_stream

    with mock.patch("tutor.run_tutor.anthropic.Anthropic", return_value=fake_client), \
         mock.patch.dict("os.environ", {"TUTOR_JSON_MODE": "off"}):
        plan = [("system_static", "SYS"), ("student", "hi")]
        list(stream_tutor_reply_anthropic_raw(plan, model_name="claude-sonnet-5", api_key="test"))
    return captured


def test_raw_stream_disables_thinking():
    """The stream call must pass thinking={"type": "disabled"} (Sonnet 5 default is adaptive)."""
    captured = _run_and_capture_stream_kwargs()
    assert captured.get("thinking") == {"type": "disabled"}, (
        f'expected thinking disabled, got: {captured.get("thinking")!r}'
    )


if __name__ == "__main__":
    test_raw_stream_disables_thinking()
    print("PASS - raw stream disables thinking")
