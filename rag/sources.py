"""Local-file source reader for RAG ingestion.

Returns the course-level text that should be *retrievable*, as labeled
``(source, text)`` documents:

- top-level ``course.txt``, ``syllabus.txt``, ``key_concepts.txt``
- every ``lectures/*.txt`` (transcripts)
- every ``exercises/*.txt`` and ``practices/*.txt`` (problem prompts)

Deliberately excluded: the ``*_solutions/`` folders (the current problem's
solution is paired into context directly — see ``utils.curriculum.read_solution``
— never surfaced by similarity), ``figures/`` (images, not text), the numpy
``rag_index/``, and metadata files (``course_name.txt``, ``online_link.txt``).
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_CURRICULUM_ROOT = _REPO_ROOT / "curriculum"

Doc = tuple[str, str]  # (source_label, text)


def load_local_docs(course: str, curriculum_root: Path | str | None = None) -> list[Doc]:
    """Collect local course/syllabus/lecture text as labeled documents."""
    root = Path(curriculum_root) if curriculum_root is not None else _DEFAULT_CURRICULUM_ROOT
    course_dir = root / course
    docs: list[Doc] = []

    for name in ("course.txt", "syllabus.txt", "key_concepts.txt"):
        path = course_dir / name
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                docs.append((f"local:{path.stem}", text))

    # Retrievable per-item folders: lecture transcripts + exercise & practice
    # prompts. Solutions live in *_solutions/ and are paired directly (not here);
    # figures/ are images; rag_index/ is the built index.
    for subdir in ("lectures", "exercises", "practices"):
        folder = course_dir / subdir
        if folder.is_dir():
            for path in sorted(folder.glob("*.txt")):
                text = path.read_text(encoding="utf-8").strip()
                if text:
                    docs.append((f"local:{path.stem}", text))

    return docs
