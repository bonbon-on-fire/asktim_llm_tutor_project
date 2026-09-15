"""Lecture- and recitation-transcript discovery shared across context builders.

A course may ship lecture transcripts under ``curriculum/<course>/lectures/`` and
recitation material under ``curriculum/<course>/recitations/`` (both plain text).
These are folded into the tutor's context so it can ground guidance in what was
actually taught, not just the exercise prompt. Per the 06/09/2026 design decision,
transcripts are included **per-course** (all lectures/recitations for the course),
mirroring how ``course.txt`` and ``syllabus.txt`` are treated.

Text-only and additive: when the folder or files are absent these return an
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


def _load_transcripts(
    course: str,
    subdir: str,
    curriculum_root: Path | str | None = None,
) -> str:
    """Return every ``*.txt`` under ``<course>/<subdir>/`` as one labeled string.

    Reads in natural (numeric) filename order, labels each block with its file
    stem, and joins with blank lines. Returns ``""`` when the folder is missing or
    holds no non-empty text.
    """
    folder = course_dir(course, curriculum_root) / subdir
    if not folder.is_dir():
        return ""

    parts: list[str] = []
    for path in sorted(folder.glob("*.txt"), key=_natural_key):
        text = path.read_text(encoding="utf-8").strip()
        if text:
            parts.append(f"[{path.stem}]\n{text}")
    return "\n\n".join(parts)


def load_lecture_transcripts(
    course: str,
    curriculum_root: Path | str | None = None,
) -> str:
    """Return all lecture transcripts for *course* concatenated into one string.

    Reads every ``*.txt`` under ``<curriculum_root>/<course>/lectures/`` in
    natural (numeric) filename order, labels each block with its file stem, and
    joins them with blank lines. Returns ``""`` when the folder is missing or empty.
    """
    return _load_transcripts(course, "lectures", curriculum_root)


def load_recitation_transcripts(
    course: str,
    curriculum_root: Path | str | None = None,
) -> str:
    """Return all recitation transcripts for *course* concatenated into one string.

    Same contract as :func:`load_lecture_transcripts`, reading
    ``<curriculum_root>/<course>/recitations/``. Returns ``""`` when the folder is
    missing or empty, so courses without recitations are unaffected.
    """
    return _load_transcripts(course, "recitations", curriculum_root)
