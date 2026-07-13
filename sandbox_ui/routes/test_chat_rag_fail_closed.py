"""Route-level test: a rag-mode turn with no retrievable material fails closed.

The real bridge stream runs; only retrieval is stubbed empty, so the base
``_enforce_rag_available`` raises ``RagUnavailableError`` and the chat route
converts it into an ``event: error`` SSE frame (no ``done`` frame).
"""

from __future__ import annotations

import ui_core.tutor_bridge as tb


def _empty_retrieval(self, course, query, **ctx):
    """Force rag mode to see no retrieved records (empty index simulation)."""
    return tb.RetrievedContext()


def test_rag_turn_without_material_emits_error_frame(client, monkeypatch):
    """A rag-mode chat turn with empty retrieval yields an SSE error frame, no done."""
    # Force rag mode and empty retrieval on the shared bridge base.
    monkeypatch.setenv("TUTOR_CONTEXT_MODE", "rag")
    monkeypatch.setattr(tb.TutorBridge, "retrieved_context", _empty_retrieval)

    resp = client.post(
        "/api/chat",
        json={
            "text": "Explain urban heat islands",
            "course": "cities_and_climate_change",
            "exercise": "4",
        },
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "event: error" in body
    assert "event: done" not in body
