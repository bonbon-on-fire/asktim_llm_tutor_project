"""Course key -> human-readable display name for database_ui.

The conversations table stores ``course`` as a curriculum *key* (the folder name,
e.g. ``cities_and_climate_change``). The display name lives in
``curriculum/<key>/course_name.txt`` and is the single source of truth for the
live apps. database_ui's image intentionally excludes ``curriculum/`` (it never
runs the tutor; it only reads the DB), so the names are mirrored here.

When adding a course: copy the contents of its ``course_name.txt`` into the map
below. Unknown keys fall back to a prettified version of the key, so a freshly
added course still renders sensibly until its name is mirrored here.
"""

from __future__ import annotations


# Mirror of curriculum/<key>/course_name.txt. Keep in sync when courses are added.
COURSE_DISPLAY_NAMES: dict[str, str] = {
    "cities_and_climate_change": "MIT 11.270x Cities and Climate Change",
    "economic_development_planning": "MIT 11.438 Economic Development Planning",
    "intro_to_international_development_planning": (
        "MIT 11.701 Introduction to International Development Planning"
    ),
    "mathematics_for_cs": "MIT 6.1200J Mathematics for Computer Science",
    "meaning_of_life": "MIT 21A.157 The Meaning of Life",
    "physics_iii_vibrations_and_waves": "MIT 8.03SC Physics III: Vibrations and Waves",
    "supply_chain_design": "MIT CTL.SC2x Supply Chain Design",
    "urban_transportation": (
        "MIT 11.943J Urban Transportation, Land Use, and the Environment"
    ),
}


def course_display_name(course_key: str | None) -> str:
    """Return the human-readable course name for a curriculum key.

    Falls back to a prettified key (``"a_b_c"`` -> ``"A B C"``) for keys not yet
    mirrored in :data:`COURSE_DISPLAY_NAMES`, and to ``""`` for a missing key.
    """
    if not course_key:
        return ""
    known = COURSE_DISPLAY_NAMES.get(course_key)
    if known:
        return known
    return course_key.replace("_", " ").replace("-", " ").strip().title()
