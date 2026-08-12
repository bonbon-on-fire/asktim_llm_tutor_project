# database_ui/analytics/tests/test_report.py
from datetime import date

from database_ui.analytics.report import render_report
from database_ui.analytics.weeks import Week


def test_report_has_headline_and_sections():
    week = Week(date(2026, 8, 9))
    stats = {
        "usage": {"conversations": 3, "unique_students": 2, "new_students": 1,
                  "returning_students": 1, "conversations_by_day": {"2026-08-10": 3}},
        "ratings": {"up": 2, "down": 1, "positive_rate": 0.667, "pct_turns_rated": 0.5},
        "cost": {"total_usd": 0.06, "per_conversation_usd": 0.02, "model_mix": {"claude-x": 3}},
        "content": {"rag_rate": 0.4, "rag_turns": 2, "tutor_prompt_mix": {"tutor_09": 3}},
        "per_course": {},
    }
    wow = {"conversations": {"arrow": "▲", "current": 3, "prior": 1, "delta": 2}}
    flags = {"items": [{"id": "a", "course": "sc", "exercise": "exercise:1", "student": "u@x",
                        "source": "both", "issue_type": "gave_away_answer", "severity": "high",
                        "quote": "just plug it in", "one_line": "gave answer"}],
             "counts_by_issue": {"gave_away_answer": 1}, "thumbs_down": 1, "judge_flagged": 1, "overlap": 1}
    topics = {"sc": [{"topic": "EOQ", "count": 2, "examples": ["how?"]}]}
    md = render_report(week, stats, wow, flags, topics, judged_count=3, judge_model="claude-sonnet-5", skipped=0)
    assert "Aug 9, 2026 — Aug 15, 2026" in md
    assert "Didn't work well" in md
    assert "gave_away_answer" in md
    assert "EOQ" in md
