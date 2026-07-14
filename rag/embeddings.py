"""OpenAI text embeddings for the RAG index.

Uses ``text-embedding-3-small`` (1536-dim) by default; override with the
``EMBEDDING_MODEL`` env var. Requires ``OPENAI_API_KEY`` (loaded from the repo
``.env`` by the apps, or by the ingest CLI). Batches inputs so a few hundred
chunks embed in a handful of API calls.
"""

from __future__ import annotations

import os

import numpy as np
from openai import OpenAI

EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Return the process-wide OpenAI client, creating it lazily on first use."""
    global _client
    if _client is None:
        _client = OpenAI()  # reads OPENAI_API_KEY from the environment
    return _client


def embed_texts_with_usage(
    texts: list[str], *, batch_size: int = 100
) -> tuple[np.ndarray, int]:
    """Embed texts into an ``(N, D)`` array plus the total prompt tokens billed.

    The token count is read from each batch's ``resp.usage.prompt_tokens`` (summed
    across batches) so callers can cost-account the embedding call exactly rather
    than estimate it. Falls back to ``0`` tokens when the provider omits usage.
    """
    if not texts:
        return np.empty((0, 0), dtype="float32"), 0
    client = _get_client()
    vectors: list[list[float]] = []
    tokens = 0
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        resp = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        vectors.extend(item.embedding for item in resp.data)
        usage = getattr(resp, "usage", None)
        tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
    return np.asarray(vectors, dtype="float32"), tokens


def embed_texts(texts: list[str], *, batch_size: int = 100) -> np.ndarray:
    """Embed a list of texts into an ``(N, D)`` float32 array."""
    vectors, _ = embed_texts_with_usage(texts, batch_size=batch_size)
    return vectors


def embed_query_with_usage(text: str) -> tuple[np.ndarray, int]:
    """Embed a query into a ``(D,)`` vector plus the prompt tokens billed for it."""
    vectors, tokens = embed_texts_with_usage([text])
    return vectors[0], tokens


def embed_query(text: str) -> np.ndarray:
    """Embed a single query string into a ``(D,)`` float32 vector."""
    return embed_query_with_usage(text)[0]
