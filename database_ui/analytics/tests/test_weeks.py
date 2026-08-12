# database_ui/analytics/tests/test_weeks.py
from datetime import date, datetime, timezone

from database_ui.analytics.weeks import (
    Week, week_containing, previous_complete_week, parse_week,
)


def test_week_containing_snaps_to_sunday():
    # Aug 12 2026 is a Wednesday; its week starts Sun Aug 9.
    assert week_containing(date(2026, 8, 12)).start == date(2026, 8, 9)
    # A Sunday maps to itself.
    assert week_containing(date(2026, 8, 9)).start == date(2026, 8, 9)
    # A Saturday still maps back to the prior Sunday.
    assert week_containing(date(2026, 8, 15)).start == date(2026, 8, 9)


def test_week_end_and_label():
    w = Week(date(2026, 8, 9))
    assert w.end == date(2026, 8, 15)
    assert w.key == "2026-08-09"
    assert w.label() == "Aug 9, 2026 — Aug 15, 2026"


def test_previous_complete_week():
    # From Wed Aug 12 2026, the previous complete week is Aug 2–8.
    assert previous_complete_week(date(2026, 8, 12)).start == date(2026, 8, 2)


def test_utc_window_is_half_open_and_dst_correct():
    w = Week(date(2026, 8, 9))  # summer -> EDT, UTC-4
    # Local Sun 00:00 EDT == 04:00 UTC.
    assert w.start_utc == datetime(2026, 8, 9, 4, 0, tzinfo=timezone.utc)
    # Exclusive end == next Sun 00:00 EDT == 04:00 UTC.
    assert w.end_utc == datetime(2026, 8, 16, 4, 0, tzinfo=timezone.utc)


def test_parse_week_snaps_and_prev():
    assert parse_week("2026-08-12").start == date(2026, 8, 9)
    assert Week(date(2026, 8, 9)).prev().start == date(2026, 8, 2)
