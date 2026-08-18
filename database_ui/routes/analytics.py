# database_ui/routes/analytics.py
"""Weekly-report blueprint: the scoped JSON API for the in-dashboard report.

The report renders in-place on the conversation dashboard (``/``); there is no
standalone page — these endpoints feed that panel via ``analytics.js``.
"""
from __future__ import annotations

from datetime import date

from flask import Blueprint, g, jsonify, request

from database_ui.analytics.weeks import parse_week, week_containing
from database_ui.auth import allowed_courses
from database_ui.courses import course_display_name
from database_ui.services import analytics as svc

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.get("/api/analytics")
def api_analytics():
    raw = request.args.get("week")
    week = parse_week(raw) if raw else week_containing(date.today())
    allowed = allowed_courses()
    # Optional multi-course filter from the report's course dropdown (one
    # course= param per selected course). Out-of-scope keys are dropped, and an
    # empty/all selection falls back to the login's full scope — so a
    # course-scoped login can never read another course's data.
    courses = _course_scope(allowed, request.args.getlist("course"))
    live = svc.live_stats(g.db, week, courses)
    cached = svc.cached_sections(week.key, courses)
    return jsonify({
        "week": {"key": week.key, "label": week.label()},
        "live": live,
        "cached": cached,
        # Curriculum-key -> human course name, so the client shows "MIT CTL.SC2x
        # Supply Chain Design" rather than the raw "supply_chain_design" key.
        "course_names": _course_names(cached),
        # Live label data (kind/number/date/msg-count) for the flagged list, so
        # each flag can render and link to its conversation. Scoped to the
        # login's courses via the already-filtered cache.
        "conversation_meta": svc.flagged_conversation_meta(g.db, cached),
    })


def _course_names(cached: dict | None) -> dict[str, str]:
    """Display-name lookup for every course key present in the cached sections."""
    if not cached:
        return {}
    keys = set(cached.get("ai_review_by_course") or {})
    keys.update(
        c.get("course") for c in (cached.get("conversations") or {}).values()
    )
    return {k: course_display_name(k) for k in keys if k}


def _course_scope(
    allowed: list[str] | None, selected: list[str] | None
) -> list[str] | None:
    """Narrow the login's scope to the chosen courses, dropping out-of-scope asks.

    ``selected`` is the raw ``course=`` values from the request. Blanks are
    stripped; keys outside ``allowed`` are dropped. If nothing selectable
    remains (no filter, or every key was out of scope), the login's full scope
    is returned unchanged — the report's "all courses" state.
    """
    sel = [s.strip() for s in (selected or []) if s and s.strip()]
    if allowed is not None:
        sel = [s for s in sel if s in allowed]
    # Preserve order while de-duplicating.
    sel = list(dict.fromkeys(sel))
    return sel or allowed


@analytics_bp.get("/api/analytics/rubric")
def api_rubric():
    """The default grading rubric (markdown) behind the Flagged card's (i) icon.

    Not course-scoped: one global rubric, identical for every login and not
    sensitive. 404 only if the rubric file is missing from the deploy.
    """
    try:
        return jsonify(svc.default_rubric())
    except FileNotFoundError:
        return jsonify({"error": "rubric unavailable"}), 404


@analytics_bp.get("/api/analytics/weeks")
def api_weeks():
    allowed = allowed_courses()
    # The calendar range tightens to a single course when one is chosen, so the
    # arrows/calendar only reach weeks that course actually has data for. The
    # dropdown's option list stays the login's full scope so it can switch back.
    scoped = _course_scope(allowed, request.args.getlist("course"))
    return jsonify({
        "weeks": svc.week_options(),
        "range": svc.week_range(g.db, scoped),
        "courses": svc.selectable_courses(g.db, allowed),
    })
