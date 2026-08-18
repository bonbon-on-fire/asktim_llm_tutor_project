# database_ui/services/analytics.py
"""Dashboard-facing analytics: live per-week stats + scoped cache reads.

Live stats are computed from the DB on every request (any week). Judged
sections come from the committed cache, course-filtered to the login's scope.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from sqlalchemy.orm import Session

from database_ui.analytics import cache as cache_mod
from database_ui.analytics import data as data_mod
from database_ui.analytics.stats import compute_stats, week_over_week
from database_ui.analytics.weeks import Week, week_containing
from database_ui.courses import course_display_name
from database_ui.services import conversations as conv_mod


def live_stats(db: Session, week: Week, courses: list[str] | None) -> dict:
    """Sections 1-4 + per-course (8) + week-over-week deltas (9), scoped."""
    convs = data_mod.fetch_conversations(db, week, courses)
    msgs = data_mod.fetch_messages(db, [c.id for c in convs])
    returning = data_mod.prior_usernames(db, week.start_utc, courses)
    stats = compute_stats(convs, msgs, returning)

    prior = week.prev()
    p_convs = data_mod.fetch_conversations(db, prior, courses)
    p_msgs = data_mod.fetch_messages(db, [c.id for c in p_convs])
    p_returning = data_mod.prior_usernames(db, prior.start_utc, courses)
    prior_stats = compute_stats(p_convs, p_msgs, p_returning)

    stats["week_over_week"] = week_over_week(stats, prior_stats)
    stats["week"] = {"key": week.key, "label": week.label(),
                     "start": week.key, "end": week.end.isoformat()}
    return stats


def cached_sections(
    week_key: str, courses: list[str] | None, *, all_access: bool = True
) -> dict | None:
    """Course-filtered judged sections for a week, or ``None`` if not generated.

    Strips the internal ``_hashes`` bookkeeping so it never leaves the server.
    The "Didn't work well" flags are internal QA, shown only in the master view;
    for a scoped (per-course) login we drop the ``conversations`` that drive them
    so the flag data never reaches that client at all.
    """
    blob = cache_mod.read_cache(week_key)
    if blob is None:
        return None
    blob.pop("_hashes", None)
    filtered = cache_mod.filter_cache(blob, courses)
    if not all_access:
        filtered = dict(filtered)
        filtered["conversations"] = {}
    return filtered


def flagged_conversation_meta(db: Session, cached: dict | None) -> dict[str, dict]:
    """Live label data for the flagged (didn't-work-well) conversations only.

    The judged cache marks conversations ``worked_well`` true/false but doesn't
    store the mutable "Practice 7 · Aug 17 · N messages" metadata. The Flagged
    list needs that to render a clickable label, so we read it live for exactly
    the flagged ids in scope (``cached['conversations']`` is already
    course-filtered, so this never reaches out of the login's scope).
    """
    convs = (cached or {}).get("conversations") or {}
    flagged = [cid for cid, c in convs.items() if not c.get("worked_well")]
    if not flagged:
        return {}
    return conv_mod.conversation_meta(db, flagged)


def selectable_courses(db: Session, courses: list[str] | None) -> list[dict]:
    """Course-filter dropdown options ``[{key, name}]`` for the login's scope.

    Only courses that actually have conversations are listed; the client adds an
    "All courses" option in front.
    """
    return [
        {"key": k, "name": course_display_name(k)}
        for k in data_mod.distinct_courses(db, courses)
    ]


def week_options() -> list[dict]:
    """Picker options: every cached week plus the current in-progress week."""
    keys = set(cache_mod.available_weeks())
    keys.add(week_containing(date.today()).key)
    return [
        {"key": k, "label": Week(date.fromisoformat(k)).label()}
        for k in sorted(keys, reverse=True)
    ]


# The single global rubric every judged conversation is scored against. Kept in
# sync with eval/tutor_judge/run_judge.py's DEFAULT_RUBRIC — the calibrated
# default the web judge adapter never overrides. Resolved as a plain file read,
# NOT by importing run_judge, which would pull the whole judging stack
# (langchain/langgraph/openai) into the web process just to read one markdown file.
_RUBRICS_DIR = Path(__file__).resolve().parents[2] / "eval" / "tutor_judge" / "rubrics"
DEFAULT_RUBRIC = "rubric_08"


def default_rubric() -> dict:
    """The grading-rubric markdown shown behind the Flagged card's (i) icon.

    Returns ``{name, title, markdown}`` for the one global default rubric — the
    same rubric that produced the flags. ``title`` is the rubric's top ``# ``
    heading. Raises ``FileNotFoundError`` if the rubric is missing from the deploy.
    """
    markdown = (_RUBRICS_DIR / f"{DEFAULT_RUBRIC}.md").read_text(encoding="utf-8")
    title = DEFAULT_RUBRIC
    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    return {"name": DEFAULT_RUBRIC, "title": title, "markdown": markdown}


def week_range(db: Session, courses: list[str] | None) -> dict:
    """Selectable week bounds for the calendar picker, scoped to the login.

    ``min`` is the week containing the earliest conversation (its Sunday key);
    ``max`` is the current in-progress week (also the default landing week), so
    live stats are visible mid-week — the AI review for that week just shows
    "coming soon" until the week closes. With no data, both collapse to the
    current week.
    """
    latest = week_containing(date.today())
    earliest = data_mod.earliest_conversation_date(db, courses)
    first = week_containing(earliest) if earliest else latest
    return {"min": min(first.key, latest.key), "max": latest.key}
