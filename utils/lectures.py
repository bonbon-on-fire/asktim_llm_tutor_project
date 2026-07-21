"""Lecture-transcript discovery shared across context builders.

A course may ship lecture transcripts (plain text) under
``curriculum/<course>/lectures/``. These are folded into the tutor's context
so it can ground guidance in what was actually taught, not just the exercise
prompt. Per the 06/09/2026 design decision, transcripts are included
**per-course** (all lectures for the course), mirroring how ``course.txt`` and
``syllabus.txt`` are treated.

Text-only and additive: when the folder or files are absent this returns an
empty string, so existing courses (and the deployed app) are unaffected.
"""

from __future__ import annotations

import re
from pathlib import Path

from utils.curriculum import course_dir


def _natural_key(path: Path) -> list:
    """Sort key that orders numeric runs by value (``lecture_2`` before ``lecture_10``).

    Filenames are no longer zero-padded, so a plain lexicographic sort would
    place ``lecture_10_...`` before ``lecture_2_...``. Splitting on digit runs
    and comparing them as integers restores the intended lecture order.
    """
    return [int(tok) if tok.isdigit() else tok for tok in re.split(r"(\d+)", path.name)]


def load_lecture_transcripts(
    course: str,
    curriculum_root: Path | str | None = None,
) -> str:
    """Return all lecture transcripts for *course* concatenated into one string.

    Reads every ``*.txt`` under ``<curriculum_root>/<course>/lectures/`` in
    natural (numeric) filename order, labels each block with its file stem, and
    joins them with blank lines. Returns ``""`` when the folder is missing or empty.
    """
    lectures_dir = course_dir(course, curriculum_root) / "lectures"
    if not lectures_dir.is_dir():
        return ""

    parts: list[str] = []
    for path in sorted(lectures_dir.glob("*.txt"), key=_natural_key):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            parts.append(f"[{path.stem}]\n{text}")
    return "\n\n".join(parts)
