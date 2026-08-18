# database_ui/routes/analytics.py
"""Weekly-report blueprint: the page shell and its scoped JSON API."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, current_app, g, jsonify, render_template, request

from database_ui.analytics.weeks import parse_week, week_containing
from database_ui.auth import allowed_courses
from database_ui.courses import course_display_name
from database_ui.routes.database import _scope_label  # reuse the hidden banner label
from database_ui.services import analytics as svc

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.get("/analytics")
def analytics_page():
    return render_template(
        "analytics.html",
        title=current_app.config["DATABASE_UI_TITLE"],
        accent=current_app.config["DATABASE_UI_ACCENT"],
        scope_label=_scope_label(),
    )


@analytics_bp.get("/api/analytics")
def api_analytics():
    raw = request.args.get("week")
    week = parse_week(raw) if raw else week_containing(date.today())
    allowed = allowed_courses()
    all_access = allowed is None          # master password / open dev, not a course scope
    # Optional multi-course filter from the report's course dropdown (one
    # course= param per selected course). Out-of-scope keys are dropped, and an
    # empty/all selection falls back to the login's full scope — so a
    # course-scoped login can never read another course's data.
    courses = _course_scope(allowed, request.args.getlist("course"))
    live = svc.live_stats(g.db, week, courses)
    cached = svc.cached_sections(week.key, courses, all_access=all_access)
    return jsonify({
        "week": {"key": week.key, "label": week.label()},
        "live": live,
        "cached": cached,
        "all_access": all_access,         # gates the master-only "Didn't work well" flags
        # Curriculum-key -> human course name, so the client shows "MIT CTL.SC2x
        # Supply Chain Design" rather than the raw "supply_chain_design" key.
        "course_names": _course_names(cached),
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
