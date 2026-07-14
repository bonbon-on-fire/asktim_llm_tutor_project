"""Cost-accounting tests for the tutor bridge and RAG embedding usage threading.

Pure/offline: builds fake LangChain messages and monkeypatches the RAG store +
embedding call. No real LLM / embedding API calls.
"""

import sys

from langchain_core.messages import AIMessage

from ui_core.tutor_bridge import _cost_for_turn

# rag/__init__.py re-exports `retrieve`, shadowing the submodule name — patch on
# the real module object from sys.modules (mirrors rag/test_week_scope.py).
import rag.retrieve  # noqa: F401  (ensure it's imported/registered)

_RETRIEVE_MOD = sys.modules["rag.retrieve"]


def _tutor_message(model: str, *, inp: int, out: int, cache_read: int = 0) -> AIMessage:
    """A tutor AIMessage carrying usage_metadata + response_metadata like the real one."""
    return AIMessage(
        content="{}",
        usage_metadata={
            "input_tokens": inp,
            "output_tokens": out,
            "total_tokens": inp + out,
            "input_token_details": {"cache_read": cache_read},
        },
        response_metadata={"model_name": model},
    )


def test_cost_prices_tutor_call_with_cache_read():
    # claude-sonnet-5: in $3, out $15, cache_read $0.30 (per 1M).
    # 200 uncached in + 800 cache-read in + 200 out:
    #   200*3 + 800*0.30 + 200*15 = 600 + 240 + 3000 = 3840 / 1e6 = 0.00384
    msg = _tutor_message("claude-sonnet-5", inp=1000, out=200, cache_read=800)
    cost = _cost_for_turn(msg, provider="claude", embedding_tokens=0)
    assert cost["model"] == "claude-sonnet-5"
    assert cost["embedding"] is None
    assert abs(cost["usd"] - 0.00384) < 1e-9
    assert abs(cost["tutor"]["usd"] - 0.00384) < 1e-9


def test_cost_adds_embedding_line_when_rag_ran():
    msg = _tutor_message("gpt-5.4", inp=500, out=100)
    # gpt-5.4: in $2.50, out $15 -> 500*2.5 + 100*15 = 1250 + 1500 = 2750 -> 0.00275
    # embedding text-embedding-3-small $0.02/1M -> 400 * 0.02 = 8 -> 0.000008
    cost = _cost_for_turn(msg, provider="gpt", embedding_tokens=400)
    assert cost["embedding"] is not None
    assert cost["embedding"]["input_tokens"] == 400
    assert abs(cost["usd"] - (0.00275 + 0.000008)) < 1e-9


def test_cost_degrades_to_zero_without_usage():
    # Canned / fallback reply: no model call, no usage. Must not crash; falls back
    # to the provider's default model id and $0.
    cost = _cost_for_turn(None, provider="gpt", embedding_tokens=0)
    assert cost["model"] == "gpt-5.4"
    assert cost["usd"] == 0.0


class _FakeChunk:
    def __init__(self, source, text):
        self.source = source
        self.text = text


class _FakeStore:
    def __init__(self, chunks):
        self.chunks = chunks

    def search(self, _vec, k):
        return [(c, 1.0 - i * 0.01) for i, c in enumerate(self.chunks)][:k]


def test_retrieve_scored_with_usage_returns_embedding_tokens(monkeypatch):
    chunks = [_FakeChunk("local:course", "abc"), _FakeChunk("local:lecture_1_1_x", "def")]
    monkeypatch.setattr(_RETRIEVE_MOD, "_get_store", lambda course: _FakeStore(chunks))
    monkeypatch.setattr(
        _RETRIEVE_MOD, "embed_query_with_usage", lambda q: ([0.0], 7)
    )
    scored, tokens = _RETRIEVE_MOD.retrieve_scored_with_usage("c", "q", k=2)
    assert len(scored) == 2
    assert tokens == 7


def test_retrieve_scored_with_usage_zero_tokens_when_no_index(monkeypatch):
    # No store -> no embedding call -> zero tokens, empty results.
    monkeypatch.setattr(_RETRIEVE_MOD, "_get_store", lambda course: None)
    scored, tokens = _RETRIEVE_MOD.retrieve_scored_with_usage("c", "q")
    assert scored == []
    assert tokens == 0
