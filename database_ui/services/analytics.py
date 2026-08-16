# database_ui/services/analytics.py
"""Dashboard-facing analytics: live per-week stats + scoped cache reads.

Live stats are computed from the DB on every request (any week). Judged
sections come from the committed cache, course-filtered to the login's scope.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from database_ui.analytics import cache as cache_mod
from database_ui.analytics import data as data_mod
from database_ui.analytics.stats import compute_stats, week_over_week
from database_ui.analytics.weeks import Week, previous_complete_week, week_containing


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


def cached_sections(week_key: str, courses: list[str] | None) -> dict | None:
    """Course-filtered judged sections for a week, or ``None`` if not generated.

    Strips the internal ``_hashes`` bookkeeping so it never leaves the server.
    """
    blob = cache_mod.read_cache(week_key)
    if blob is None:
        return None
    blob.pop("_hashes", None)
    return cache_mod.filter_cache(blob, courses)


def week_options() -> list[dict]:
    """Picker options: every cached week plus the default previous-complete week."""
    keys = set(cache_mod.available_weeks())
    keys.add(previous_complete_week(date.today()).key)
    return [
        {"key": k, "label": Week(date.fromisoformat(k)).label()}
        for k in sorted(keys, reverse=True)
    ]


def week_range(db: Session, courses: list[str] | None) -> dict:
    """Selectable week bounds for the calendar picker, scoped to the login.

    ``min`` is the week containing the earliest conversation (its Sunday key);
    ``max`` is the latest complete week (also the default). With no data, both
    collapse to the default week.
    """
    latest = previous_complete_week(date.today())
    earliest = data_mod.earliest_conversation_date(db, courses)
    first = week_containing(earliest) if earliest else latest
    return {"min": min(first.key, latest.key), "max": latest.key}
