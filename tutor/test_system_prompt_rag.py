r"""Tests: per-turn RAG context is delivered via the SYSTEM message, not a user turn.

The meeting decision (2026-07-12) was to move retrieved course material off the
student's turn and into the tutor's instruction channel. LangChain has no
developer-message type, so we fold it into the system message — appended AFTER
the static, cacheable prompt so prompt caching still hits on the static prefix
and only the fresh RAG block is re-read each turn.
"""

import json

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

from tutor.run_tutor import _build_system_message, get_tutor_reply, stream_tutor_reply

_CANNED = json.dumps(
    {"pedagogical-reasoning": "r", "Student-facing-answer": "ok"}
)


# --- _build_system_message: OpenAI / non-Anthropic (string system) ---

def test_openai_system_message_appends_rag_after_static_prefix():
    # A non-ChatAnthropic model (here a sentinel) takes the string branch.
    msg = _build_system_message("BASE_PROMPT", "FAKE_OPENAI_MODEL", retrieved_context="RAG_BLOCK")
    assert isinstance(msg.content, str)
    # Static stays the prefix so OpenAI prefix-caching still matches across turns.
    assert msg.content.startswith("BASE_PROMPT")
    assert "RAG_BLOCK" in msg.content


def test_openai_system_message_without_rag_is_unchanged():
    msg = _build_system_message("BASE_PROMPT", "FAKE_OPENAI_MODEL")
    assert msg.content == "BASE_PROMPT"


# --- _build_system_message: Anthropic (block list, cache_control) ---

def _anthropic_model():
    # Construction is offline (no network); a placeholder key is enough.
    return ChatAnthropic(model="claude-sonnet-4-6", api_key="test-key")


def test_anthropic_system_keeps_static_cached_and_rag_uncached():
    msg = _build_system_message("BASE_PROMPT", _anthropic_model(), retrieved_context="RAG_BLOCK")
    assert isinstance(msg.content, list) and len(msg.content) == 2
    static, rag = msg.content
    # Static prompt keeps the cache breakpoint...
    assert static["text"] == "BASE_PROMPT"
    assert static["cache_control"] == {"type": "ephemeral"}
    # ...and the per-turn RAG block sits after it, NOT cached.
    assert rag["text"] == "RAG_BLOCK"
    assert "cache_control" not in rag


def test_anthropic_system_without_rag_is_single_cached_block():
    msg = _build_system_message("BASE_PROMPT", _anthropic_model())
    assert isinstance(msg.content, list) and len(msg.content) == 1
    assert msg.content[0]["cache_control"] == {"type": "ephemeral"}


# --- threading: get_tutor_reply (graph path) puts RAG into graph state ---

def test_get_tutor_reply_threads_retrieved_context_into_graph_state():
    from langchain_core.messages import AIMessage

    class FakeGraph:
        def __init__(self):
            self.invoked = None

        def invoke(self, state):
            self.invoked = state
            return {"messages": [AIMessage(content=_CANNED)]}

    g = FakeGraph()
    get_tutor_reply([HumanMessage(content="hi")], graph=g, retrieved_context="RAGX")
    assert g.invoked.get("retrieved_context") == "RAGX"


# --- threading: stream_tutor_reply puts RAG in the system message ---

def test_stream_tutor_reply_puts_retrieved_context_in_system_message():
    captured = {}

    class _Chunk:
        content = _CANNED

    class FakeModel:
        def stream(self, messages):
            captured["system"] = messages[0]
            yield _Chunk()

    list(
        stream_tutor_reply(
            [HumanMessage(content="hi")],
            model=FakeModel(),
            system_prompt="BASE",
            retrieved_context="RAGZ",
        )
    )
    sysmsg = captured["system"]
    # FakeModel isn't ChatAnthropic -> string system with RAG appended after BASE.
    assert "BASE" in sysmsg.content and "RAGZ" in sysmsg.content
