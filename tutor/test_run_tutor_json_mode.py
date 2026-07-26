# tutor/test_run_tutor_json_mode.py
import json
from types import SimpleNamespace
from unittest.mock import patch

from langchain_core.messages import AIMessage, AIMessageChunk

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
    # Extended thinking stays disabled on the enforced (tool-forcing) path too —
    # otherwise thinking blocks can burn the max_tokens budget before the tool
    # input is emitted, leaving the stream empty.
    assert _FakeClient.captured["thinking"] == {"type": "disabled"}
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


def test_tool_input_from_message_none_when_input_empty():
    empty_block = SimpleNamespace(type="tool_use", name=rt.TUTOR_TOOL_NAME, input={})
    fake_msg = SimpleNamespace(content=[empty_block])
    assert rt._tool_input_from_message(fake_msg) is None

    nonempty_block = SimpleNamespace(
        type="tool_use",
        name=rt.TUTOR_TOOL_NAME,
        input={"pedagogical-reasoning": "r", "Student-facing-answer": "a"},
    )
    fake_msg_ok = SimpleNamespace(content=[nonempty_block])
    assert rt._tool_input_from_message(fake_msg_ok) == {
        "pedagogical-reasoning": "r",
        "Student-facing-answer": "a",
    }


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
