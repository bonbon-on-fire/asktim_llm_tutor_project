"""Query-time retrieval over a per-course RAG index.

Loads the course's numpy index (cached in-process), embeds the student query,
and returns the most relevant chunks under a character budget. ``format_context``
renders them into the block that tutor_bridge injects on the latest student turn.
"""

from __future__ import annotations

import json
import re

from rag.chunking import Chunk
from rag.embeddings import embed_query_with_usage
from rag.store import NumpyVectorStore
from utils.curriculum import course_dir

# Per-course store cache so we load each index from disk only once per process.
_STORE_CACHE: dict[str, NumpyVectorStore | None] = {}

# Per-course map: RAG source label -> {week, lesson, video, video_title, citation}.
# Built from the live course structure (see curriculum/<course>/lecture_index.json);
# lets citations use the real "Week 10, Lesson 1 · Video 7: DuPont Analysis" labels a
# student can actually find, instead of the synthetic "Lecture 10.6" flat index.
_LECTURE_INDEX_CACHE: dict[str, dict[str, dict]] = {}


def _lecture_index(course: str) -> dict[str, dict]:
    """Return the cached lecture index for *course* ({} if the course has none).

    Resolves into ``curriculum/_archive/<course>/`` for an archived course, same
    as every other course-relative path here.
    """
    if course not in _LECTURE_INDEX_CACHE:
        path = course_dir(course) / "lecture_index.json"
        try:
            _LECTURE_INDEX_CACHE[course] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _LECTURE_INDEX_CACHE[course] = {}
    return _LECTURE_INDEX_CACHE[course]

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


# Human-readable citation labels. ``local:lecture_1_1_the_transportation_problem``
# -> ``Lecture 1.1 The Transportation Problem`` (week.seq + title-cased topic), so
# the tutor can cite what it retrieved (see the tutor prompt's citation rule).
_LECTURE_RE = re.compile(r"^local:lecture_(\d+)_(\d+)_(.+)$")
_NUMBERED_RE = re.compile(r"^local:(practice|exercise)_(\d+)$")
_NAMED_LABELS = {
    "local:course": "Course overview",
    "local:syllabus": "Syllabus",
    "local:key_concepts": "Key Concepts Document",
}
# Slug tokens that should stay uppercase rather than title-cased (Roic, Milp, ...).
_ACRONYMS = {
    "roic", "roi", "milp", "mrp", "drp", "fph", "atp", "bom", "dc", "dcs",
    "sc1x", "sc2x", "ocw", "kpi", "cogs", "sku", "eoq", "lp", "mip",
}


def _titleize(slug: str) -> str:
    """Turn a ``the_transportation_problem`` slug into ``The Transportation Problem``.

    Each ``_``-separated word is capitalized, except known acronyms which are
    uppercased. Not a full title-caser (small words like "of" get capitalized) —
    the lecture *number* is what matters; the title is a readable hint.
    """
    words = slug.split("_")
    return " ".join(w.upper() if w in _ACRONYMS else w.capitalize() for w in words if w)


def _source_label(source: str, course: str | None = None) -> str:
    """Render a raw chunk source as a human-readable, citeable label.

    When *course* has a ``lecture_index.json`` entry for this source, its
    ``citation`` (the real "Week 10, Lesson 1 · Video 7: DuPont Analysis"
    coordinate) is used. Otherwise falls back to a label derived from the stem:
    ``local:lecture_1_1_the_transportation_problem`` -> ``Lecture 1.1 The
    Transportation Problem``; ``local:practice_4`` -> ``Practice 4``;
    ``local:course``/``syllabus``/``key_concepts`` -> friendly names; OCW and
    anything unrecognized keep their label (minus a ``local:`` prefix).
    """
    s = source or ""
    if course:
        entry = _lecture_index(course).get(s)
        if entry and entry.get("citation"):
            return entry["citation"]
    m = _LECTURE_RE.match(s)
    if m:
        return f"Lecture {m.group(1)}.{m.group(2)} {_titleize(m.group(3))}"
    m = _NUMBERED_RE.match(s)
    if m:
        return f"{m.group(1).capitalize()} {m.group(2)}"
    if s in _NAMED_LABELS:
        return _NAMED_LABELS[s]
    return s.split("local:", 1)[1] if s.startswith("local:") else s


def _get_store(course: str) -> NumpyVectorStore | None:
    """Return the cached vector store for *course*, loading it from disk once."""
    if course not in _STORE_CACHE:
        _STORE_CACHE[course] = NumpyVectorStore.load(course)
    return _STORE_CACHE[course]


def has_index(course: str) -> bool:
    """True if a built RAG index exists for *course*."""
    return _get_store(course) is not None


def retrieve_scored_with_usage(
    course: str, query: str, *, k: int = 3, max_chars: int = 8000, max_week: int | None = None
) -> tuple[list[tuple[Chunk, float]], int]:
    """Like :func:`retrieve_scored`, but also returns the query-embedding tokens billed.

    The second element is the exact prompt-token count of the one embedding call
    made for *query* (``0`` when there's no index / empty query, so no call is
    made). Callers that cost-account a turn use this; :func:`retrieve_scored`
    delegates here and drops it.
    """
    store = _get_store(course)
    if store is None or not query.strip():
        return [], 0
    query_vec, embed_tokens = embed_query_with_usage(query)
    if max_week is None:
        hits = store.search(query_vec, k)
    else:
        # Over-fetch the whole ranked list, drop future-week chunks, THEN take the
        # top-k — filtering after a top-k search would let a future-week hit
        # displace an in-scope one.
        ranked = store.search(query_vec, len(store.chunks))
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
    return out, embed_tokens


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
    scored, _ = retrieve_scored_with_usage(
        course, query, k=k, max_chars=max_chars, max_week=max_week
    )
    return scored


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


def format_context(chunks: list[Chunk], course: str | None = None) -> str:
    """Render retrieved chunks into a labeled 'Relevant course material' block.

    When *course* is given, lecture entries are labeled with their real
    Week/Lesson/Video citation from ``lecture_index.json``.
    """
    if not chunks:
        return ""
    blocks = [f"[{_source_label(c.source, course)}]\n{c.text}" for c in chunks]
    return "Relevant course material:\n\n" + "\n\n".join(blocks)
