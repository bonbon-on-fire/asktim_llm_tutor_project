# database_ui/analytics/cache.py
"""Read/write and scope-filter the committed weekly cache.

The cache is the interface between the offline weekly job (producer) and the
dashboard (consumer). One JSON file per week, named by the week's start date,
committed under database_ui so it ships in the read-only image.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from database_ui.analytics.weeks import Week

CACHE_VERSION = 1
CACHE_DIR = Path(__file__).resolve().parent / "cache"


def cache_path(week_key: str) -> Path:
    return CACHE_DIR / f"{week_key}.json"


def write_cache(
    week: Week,
    judged: dict[str, dict],
    examples: dict,
    topics_by_course: dict,
    *,
    judge_model: str,
    generated_at: datetime,
    judged_count: int,
    skipped: int,
) -> Path:
    """Serialize one week's judged output to its cache file; returns the path."""
    blob = {
        "version": CACHE_VERSION,
        "week_start": week.key,
        "week_end": week.end.isoformat(),
        "tz": "America/New_York",
        "generated_at": generated_at.isoformat(),
        "judge_model": judge_model,
        "judged_count": judged_count,
        "skipped": skipped,
        "conversations": judged,
        "examples": examples,
        "topics_by_course": topics_by_course,
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = cache_path(week.key)
    path.write_text(json.dumps(blob, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_cache(week_key: str) -> dict | None:
    """Load a week's cache blob, or ``None`` if it hasn't been generated yet."""
    path = cache_path(week_key)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def filter_cache(blob: dict, courses: list[str] | None) -> dict:
    """Return a copy of ``blob`` limited to ``courses`` (``None`` = no filter).

    Conversations outside scope are removed; example id-lists and per-course
    topic maps are pruned to match, so a scoped reviewer never sees another
    course's flagged conversations, examples, or topics.
    """
    if courses is None:
        return blob
    allowed = set(courses)
    convs = {
        cid: v for cid, v in blob.get("conversations", {}).items()
        if v.get("course") in allowed
    }
    keep = set(convs)
    ex = blob.get("examples", {})
    examples = {
        "exemplary": [i for i in ex.get("exemplary", []) if i in keep],
        "high_engagement": [i for i in ex.get("high_engagement", []) if i in keep],
        "sample": {
            course: ids for course, ids in ex.get("sample", {}).items()
            if course in allowed
        },
    }
    topics = {
        course: rows for course, rows in blob.get("topics_by_course", {}).items()
        if course in allowed
    }
    out = dict(blob)
    out["conversations"] = convs
    out["examples"] = examples
    out["topics_by_course"] = topics
    return out


def available_weeks() -> list[str]:
    """Cache week-keys present on disk, newest first."""
    if not CACHE_DIR.exists():
        return []
    keys = [p.stem for p in CACHE_DIR.glob("*.json")]
    return sorted(keys, reverse=True)
