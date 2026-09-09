"""Course key -> human-readable display name for database_ui.

The conversations table stores ``course`` as a curriculum *key* (the folder
name, e.g. ``supply_chain_design``). The display name is
``curriculum/<key>/course_name.txt`` -- the single source of truth for the live
apps.

database_ui never runs the tutor, so its image excludes the bulk of
``curriculum/`` (pinned prompts, exercises, RAG indexes). It *does* bundle the
tiny ``course_name.txt`` files -- see ``Dockerfile_database`` -- so display names
stay in sync automatically: adding or renaming a course needs no edit here.
Archived courses, whose conversations still appear in the DB, resolve from
``curriculum/_archive/<key>/course_name.txt`` (an active course wins over an
archived one of the same slug, matching ``utils.curriculum.course_dir``).

Unknown keys -- a course whose name file didn't ship, or a slug retired before
the archive existed -- fall back to a prettified key so the row still renders.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path


_CURRICULUM_DIR = Path(__file__).resolve().parents[1] / "curriculum"
_ARCHIVE_DIRNAME = "_archive"


def _prettify(course_key: str) -> str:
    """``"a_b-c"`` -> ``"A B C"`` -- the last-resort label for an unknown key."""
    return course_key.replace("_", " ").replace("-", " ").strip().title()


@lru_cache(maxsize=None)
def _read_course_name(course_key: str) -> str:
    """Bundled ``course_name.txt`` for a key, or ``""`` when none shipped.

    Checks the active location first, then the archive, so a slug present in both
    resolves to the active copy (see :func:`utils.curriculum.course_dir`). Cached
    for the life of the process: the name files are immutable within an image.
    """
    for path in (
        _CURRICULUM_DIR / course_key / "course_name.txt",
        _CURRICULUM_DIR / _ARCHIVE_DIRNAME / course_key / "course_name.txt",
    ):
        if path.is_file():
            name = path.read_text(encoding="utf-8").strip()
            if name:
                return name
    return ""


def course_display_name(course_key: str | None) -> str:
    """Return the human-readable course name for a curriculum key.

    Reads the ``course_name.txt`` bundled into the image (active or archived) and
    falls back to a prettified key (``"a_b_c"`` -> ``"A B C"``) when no name file
    is present. Returns ``""`` for a missing key.
    """
    if not course_key:
        return ""
    return _read_course_name(course_key) or _prettify(course_key)
