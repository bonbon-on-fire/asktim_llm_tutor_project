# database_ui/analytics/weeks.py
"""Sunday-to-Saturday week math in America/New_York for the weekly report.

The DB stores tz-aware UTC timestamps. A "week" is a local Sun 00:00 -> next
Sun 00:00 half-open interval; we expose its UTC bounds so queries stay portable
(no DB-side timezone functions). Labels render as ``Aug 9, 2026 — Aug 15, 2026``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
_UTC = ZoneInfo("UTC")


def _fmt(d: date) -> str:
    """``date(2026, 8, 9)`` -> ``"Aug 9, 2026"`` (abbrev month, no zero-pad day)."""
    return f"{d.strftime('%b')} {d.day}, {d.year}"


@dataclass(frozen=True)
class Week:
    """A Sunday-anchored calendar week. ``start`` must be a Sunday."""

    start: date

    @property
    def end(self) -> date:
        """The inclusive Saturday that ends the week."""
        return self.start + timedelta(days=6)

    @property
    def key(self) -> str:
        """Stable identifier / cache filename stem, e.g. ``"2026-08-09"``."""
        return self.start.isoformat()

    @property
    def start_utc(self) -> datetime:
        """Local Sunday 00:00, expressed as a UTC instant (inclusive lower bound)."""
        return datetime.combine(self.start, time.min, TZ).astimezone(_UTC)

    @property
    def end_utc(self) -> datetime:
        """Next local Sunday 00:00 as a UTC instant (exclusive upper bound)."""
        nxt = self.start + timedelta(days=7)
        return datetime.combine(nxt, time.min, TZ).astimezone(_UTC)

    def label(self) -> str:
        """Human range, e.g. ``"Aug 9, 2026 — Aug 15, 2026"``."""
        return f"{_fmt(self.start)} — {_fmt(self.end)}"

    def prev(self) -> "Week":
        """The immediately preceding week."""
        return Week(self.start - timedelta(days=7))


def week_containing(d: date) -> Week:
    """The Sun–Sat week that contains ``d``. Python weekday: Mon=0..Sun=6."""
    days_since_sunday = (d.weekday() + 1) % 7
    return Week(d - timedelta(days=days_since_sunday))


def previous_complete_week(today: date) -> Week:
    """The most recent week that has fully ended as of ``today``."""
    return week_containing(today).prev()


def parse_week(s: str) -> Week:
    """Parse ``YYYY-MM-DD`` and snap to its containing week's Sunday."""
    return week_containing(date.fromisoformat(s.strip()))
