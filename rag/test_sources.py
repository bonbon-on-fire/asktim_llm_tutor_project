"""Unit tests for local RAG source discovery (which folders are retrievable)."""

from rag.sources import load_local_docs


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_readings_are_retrievable_alongside_lectures(tmp_path):
    course = tmp_path / "demo_course"
    _write(course / "lectures" / "lecture_1_1_intro.txt", "lecture text")
    _write(course / "readings" / "reading_1_jagged_frontier.txt", "reading text")
    _write(course / "practices" / "practice_2.txt", "practice text")

    sources = {label for label, _ in load_local_docs("demo_course", tmp_path)}
    assert "local:reading_1_jagged_frontier" in sources
    assert "local:lecture_1_1_intro" in sources
    assert "local:practice_2" in sources


def test_pinned_and_exercises_stay_out_of_the_index(tmp_path):
    course = tmp_path / "demo_course"
    _write(course / "readings" / "reading_1_paper.txt", "reading text")
    # These are paired directly into tutor context and must NOT be retrievable.
    _write(course / "pinned" / "syllabus.txt", "syllabus")
    _write(course / "exercises" / "exercise_1.txt", "graded prompt")

    sources = {label for label, _ in load_local_docs("demo_course", tmp_path)}
    assert "local:reading_1_paper" in sources
    assert "local:syllabus" not in sources
    assert "local:exercise_1" not in sources


def test_empty_reading_files_are_skipped(tmp_path):
    course = tmp_path / "demo_course"
    _write(course / "readings" / "reading_1_blank.txt", "   \n")
    _write(course / "readings" / "reading_1_real.txt", "actual content")

    sources = {label for label, _ in load_local_docs("demo_course", tmp_path)}
    assert "local:reading_1_real" in sources
    assert "local:reading_1_blank" not in sources
