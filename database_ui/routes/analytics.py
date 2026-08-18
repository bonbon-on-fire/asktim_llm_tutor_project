# database_ui/routes/analytics.py
"""Weekly-report blueprint: the page shell and its scoped JSON API."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, current_app, g, jsonify, render_template, request

from database_ui.analytics.weeks import parse_week, week_containing
from database_ui.auth import allowed_courses
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
    courses = allowed_courses()
    all_access = courses is None          # master password / open dev, not a course scope
    live = svc.live_stats(g.db, week, courses)
    cached = svc.cached_sections(week.key, courses, all_access=all_access)
    return jsonify({
        "week": {"key": week.key, "label": week.label()},
        "live": live,
        "cached": cached,
        "all_access": all_access,         # gates the master-only "Didn't work well" flags
    })


@analytics_bp.get("/api/analytics/weeks")
def api_weeks():
    return jsonify({
        "weeks": svc.week_options(),
        "range": svc.week_range(g.db, allowed_courses()),
    })
