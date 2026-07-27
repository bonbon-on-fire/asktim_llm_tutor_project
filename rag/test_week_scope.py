"""Unit tests for week parsing used to scope RAG retrieval to reached weeks."""

import sys

from rag.retrieve import _source_label, _source_week, format_context, retrieve_scored

# rag/__init__.py re-exports the `retrieve` function, which shadows the submodule
# name — so patch on the real module object from sys.modules, not `rag.retrieve`.
_RETRIEVE_MOD = sys.modules["rag.retrieve"]


class _FakeChunk:
    def __init__(self, source, text):
        self.source = source
        self.text = text


class _FakeStore:
    """Returns chunks in a fixed 'ranked' order, so retrieve_scored is deterministic."""

    def __init__(self, chunks):
        self.chunks = chunks

    def search(self, _vec, k):
        return [(c, 1.0 - i * 0.01) for i, c in enumerate(self.chunks)][:k]


def test_max_week_drops_future_lectures_keeps_course_level(monkeypatch):
    chunks = [
        _FakeChunk("local:lecture_1_0_intro", "w1"),
        _FakeChunk("local:lecture_2_3_model", "w2"),
        _FakeChunk("local:lecture_3_1_future", "w3"),
        _FakeChunk("local:practice_10", "w10 practice"),
        _FakeChunk("local:course", "course-level, no week"),
    ]
    monkeypatch.setattr(_RETRIEVE_MOD, "_get_store", lambda course: _FakeStore(chunks))
    # retrieve_scored now embeds via embed_query_with_usage -> (vector, tokens).
    monkeypatch.setattr(_RETRIEVE_MOD, "embed_query_with_usage", lambda q: ([0.0], 3))

    # No cutoff: every chunk is eligible.
    assert len(retrieve_scored("c", "q", k=5)) == 5

    # Cutoff at week 2: weeks 3 and 10 dropped; weeks 1-2 and course-level kept.
    srcs = {c.source for c, _ in retrieve_scored("c", "q", k=5, max_week=2)}
    assert "local:lecture_3_1_future" not in srcs
    assert "local:practice_10" not in srcs
    assert {"local:lecture_1_0_intro", "local:lecture_2_3_model", "local:course"} <= srcs


def test_lecture_week_parsed():
    assert _source_week("local:lecture_2_3_building_the_model") == 2
    assert _source_week("local:lecture_10_5_ratio_analysis") == 10


def test_practice_and_exercise_week_parsed():
    assert _source_week("local:practice_4") == 4
    assert _source_week("local:exercise_7") == 7


def test_source_label_lecture_number_and_title():
    assert (
        _source_label("local:lecture_1_1_the_transportation_problem")
        == "Lecture 1.1 The Transportation Problem"
    )
    # acronyms stay uppercase, not "Roic"
    assert _source_label("local:lecture_10_7_roic") == "Lecture 10.7 ROIC"


def test_source_label_practice_named_and_ocw():
    assert _source_label("local:practice_4") == "Practice 4"
    assert _source_label("local:course") == "Course overview"
    assert _source_label("local:syllabus") == "Syllabus"
    assert _source_label("local:key_concepts") == "Key Concepts Document"
    # OCW / unrecognized labels are left intact
    assert _source_label("ocw:https://ocw.mit.edu/x") == "ocw:https://ocw.mit.edu/x"


def test_format_context_shows_labels_not_raw_stems():
    out = format_context([_FakeChunk("local:lecture_1_1_the_transportation_problem", "flow text")])
    assert "[Lecture 1.1 The Transportation Problem]" in out
    assert "local:lecture" not in out  # the raw stem is never shown to the tutor


def test_week_agnostic_sources_return_none():
    # course-level docs and OCW content carry no week -> always in scope
    assert _source_week("local:course") is None
    assert _source_week("local:syllabus") is None
    assert _source_week("local:key_concepts") is None
    assert _source_week("ocw:https://ocw.mit.edu/...") is None
    assert _source_week("") is None
