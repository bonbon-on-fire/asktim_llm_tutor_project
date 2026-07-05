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


def embed_texts(texts: list[str], *, batch_size: int = 100) -> np.ndarray:
    """Embed a list of texts into an ``(N, D)`` float32 array."""
    if not texts:
        return np.empty((0, 0), dtype="float32")
    client = _get_client()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        resp = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        vectors.extend(item.embedding for item in resp.data)
    return np.asarray(vectors, dtype="float32")


def embed_query(text: str) -> np.ndarray:
    """Embed a single query string into a ``(D,)`` float32 vector."""
    return embed_texts([text])[0]
