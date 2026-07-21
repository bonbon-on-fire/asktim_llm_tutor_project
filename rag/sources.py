"""Local-file source reader for RAG ingestion.

Returns the course-level text that should be *retrievable*, as labeled
``(source, text)`` documents:

- top-level ``key_concepts.txt`` (too large to pin, so reached via retrieval)
- every ``lectures/*.txt`` (transcripts)
- every ``practices/*.txt`` (practice-problem prompts)

Deliberately excluded because they are paired directly into tutor context and must
not also be retrieved (that would waste the top-k budget re-fetching content
already present): the ``pinned/*.txt`` reference docs — the course description
(``pinned/course.txt``), the syllabus (``pinned/syllabus.txt``), and any other
always-on material — which are pinned every turn in ``full_context`` and ``rag``
modes (see ``ui_core.tutor_bridge`` / ``sandbox_ui.services.tutor_bridge``
``build_assignment_text`` and ``utils.curriculum.read_pinned_context``); the
``exercises/*.txt`` graded-problem prompts (the exercise the student is working on
is paired directly, so retrieval must not surface it or any *other* graded
exercise); and the ``*_solutions/`` folders (the current problem's solution is
paired the same way — see ``utils.curriculum.read_solution`` — never surfaced by
similarity). Also excluded: ``figures/`` (images, not text), the numpy
``rag_index/``, and metadata files (``course_name.txt``, ``online_link.txt``).
"""

from __future__ import annotations

from pathlib import Path

from utils.curriculum import course_dir as _course_dir

Doc = tuple[str, str]  # (source_label, text)


def load_local_docs(course: str, curriculum_root: Path | str | None = None) -> list[Doc]:
    """Collect local key-concepts/lecture/practice text as labeled documents."""
    course_dir = _course_dir(course, curriculum_root)
    docs: list[Doc] = []

    # The pinned/*.txt reference docs (course description, syllabus, …) are pinned
    # directly into tutor context (full_context and rag modes), so they're
    # intentionally NOT retrievable — retrieving a chunk of a doc that's already
    # fully in context would waste a top-k slot. key_concepts is too large to pin,
    # so it stays retrievable.
    for name in ("key_concepts.txt",):
        path = course_dir / name
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                docs.append((f"local:{path.stem}", text))

    # Retrievable per-item folders: lecture transcripts + practice-problem
    # prompts. exercises/ (graded prompts) and *_solutions/ are paired directly
    # into context, not retrieved; figures/ are images; rag_index/ is the index.
    for subdir in ("lectures", "practices"):
        folder = course_dir / subdir
        if folder.is_dir():
            for path in sorted(folder.glob("*.txt")):
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    docs.append((f"local:{path.stem}", text))

    return docs
