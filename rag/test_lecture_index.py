"""Validate lecture_index.json and its use in citation labels.

The index is hand-derived from the live course structure, so a stem typo or a
stale entry would silently mislabel a citation. These tests fail loudly if any
index key stops resolving to a real lecture file, and lock in that
``_source_label`` prefers the index's real Week/Lesson/Video citation.
"""

import json
from pathlib import Path

import pytest

from rag.retrieve import _source_label

_CURRICULUM = Path(__file__).resolve().parents[1] / "curriculum"


def _courses_with_index():
    return sorted(p.parent.name for p in _CURRICULUM.glob("*/lecture_index.json"))


@pytest.mark.parametrize("course", _courses_with_index())
def test_every_index_key_resolves_to_a_lecture_file(course):
    index = json.loads((_CURRICULUM / course / "lecture_index.json").read_text(encoding="utf-8"))
    lectures = _CURRICULUM / course / "lectures"
    assert index, f"{course}/lecture_index.json is empty"
    for key, entry in index.items():
        assert key.startswith("local:lecture_"), f"unexpected index key: {key}"
        stem = key.split("local:", 1)[1]
        assert (lectures / f"{stem}.txt").is_file(), f"{course}: {key} has no lecture file"
        assert entry.get("week"), f"{course}: {key} missing week"
        assert entry.get("citation"), f"{course}: {key} missing citation"


def test_source_label_uses_index_citation_when_course_given():
    # supply_chain_design ships the index; this is the real, findable label.
    assert (
        _source_label("local:lecture_10_6_dupont_analysis", "supply_chain_design")
        == "Week 10, Lesson 1 · Video 7: DuPont Analysis"
    )


def test_source_label_falls_back_without_course():
    # No course -> legacy stem-derived label (unchanged behavior for callers
    # that don't pass a course, and for courses with no index).
    assert (
        _source_label("local:lecture_10_6_dupont_analysis")
        == "Lecture 10.6 Dupont Analysis"
    )
    assert (
        _source_label("local:lecture_10_6_dupont_analysis", "no_such_course")
        == "Lecture 10.6 Dupont Analysis"
    )
