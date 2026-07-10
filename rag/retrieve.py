"""Query-time retrieval over a per-course RAG index.

Loads the course's numpy index (cached in-process), embeds the student query,
and returns the most relevant chunks under a character budget. ``format_context``
renders them into the block that tutor_bridge injects on the latest student turn.
"""

from __future__ import annotations

import re

from rag.chunking import Chunk
from rag.embeddings import embed_query
from rag.store import NumpyVectorStore

# Per-course store cache so we load each index from disk only once per process.
_STORE_CACHE: dict[str, NumpyVectorStore | None] = {}

# ``local:lecture_<week>_<seq>_...`` and ``local:practice_<week>`` encode the
# course week (module) as their first number; exercise_<N> shares it too. Used to
# scope retrieval to weeks the student has reached — see ``max_week`` below.
_WEEK_RE = re.compile(r"^local:(?:lecture|practice|exercise)_(\d+)")


def _source_week(source: str) -> int | None:
    """Week number encoded in a source label, or None for week-agnostic material.

    ``local:lecture_2_3_...`` -> 2, ``local:practice_4`` -> 4. Returns None for
    course-level docs (``course``/``syllabus``/``key_concepts``) and OCW content,
    which carry no week and are always in scope.
    """
    m = _WEEK_RE.match(source or "")
    return int(m.group(1)) if m else None


def _get_store(course: str) -> NumpyVectorStore | None:
    """Return the cached vector store for *course*, loading it from disk once."""
    if course not in _STORE_CACHE:
        _STORE_CACHE[course] = NumpyVectorStore.load(course)
    return _STORE_CACHE[course]


def has_index(course: str) -> bool:
    """True if a built RAG index exists for *course*."""
    return _get_store(course) is not None


def retrieve_scored(
    course: str, query: str, *, k: int = 3, max_chars: int = 8000, max_week: int | None = None
) -> list[tuple[Chunk, float]]:
    """Return up to *k* ``(chunk, cosine_score)`` pairs for *query*, capped at *max_chars*.

    When *max_week* is set, lecture/practice material from a **later** week than
    *max_week* is dropped before the top-*k* is taken — so the tutor never
    retrieves content the student hasn't reached yet. Week-agnostic docs (course
    description, syllabus, key concepts, OCW) are always in scope.

    Returns ``[]`` when there's no index or the query is empty — callers fall
    back to their non-RAG context path.
    """
    store = _get_store(course)
    if store is None or not query.strip():
        return []
    if max_week is None:
        hits = store.search(embed_query(query), k)
    else:
        # Over-fetch the whole ranked list, drop future-week chunks, THEN take the
        # top-k — filtering after a top-k search would let a future-week hit
        # displace an in-scope one.
        ranked = store.search(embed_query(query), len(store.chunks))
        hits = [
            (c, s)
            for c, s in ranked
            if (_source_week(c.source) is None or _source_week(c.source) <= max_week)
        ][:k]
    out: list[tuple[Chunk, float]] = []
    total = 0
    for chunk, score in hits:
        if out and total + len(chunk.text) > max_chars:
            break
        out.append((chunk, score))
        total += len(chunk.text)
    return out


def retrieve(
    course: str, query: str, *, k: int = 3, max_chars: int = 8000, max_week: int | None = None
) -> list[Chunk]:
    """Return up to *k* relevant chunks for *query*, capped at *max_chars* total."""
    return [c for c, _ in retrieve_scored(course, query, k=k, max_chars=max_chars, max_week=max_week)]


def to_records(scored: list[tuple[Chunk, float]]) -> list[dict]:
    """Serialize scored chunks into JSON-friendly retrieval records.

    One dict per retrieved chunk: its source label, cosine score, char length,
    and full text — the shape persisted into transcripts and the sandbox DB so
    you can see exactly what RAG pulled for each turn.
    """
    return [
        {
            "source": chunk.source,
            "score": round(float(score), 4),
            "chars": len(chunk.text),
            "text": chunk.text,
        }
        for chunk, score in scored
    ]


def format_context(chunks: list[Chunk]) -> str:
    """Render retrieved chunks into a labeled 'Relevant course material' block."""
    if not chunks:
        return ""
    blocks = [f"[{c.source}]\n{c.text}" for c in chunks]
    return "Relevant course material (retrieved):\n\n" + "\n\n".join(blocks)
