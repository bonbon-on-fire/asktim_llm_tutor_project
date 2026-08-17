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
                        "quote": "just plug it in", "one_line": "gave answer", "score": 18}],
             "counts_by_issue": {"gave_away_answer": 1}, "thumbs_down": 1, "judge_flagged": 1, "overlap": 1,
             "avg_score": {"avg": 27.5, "max": 40, "n": 3}}
    topics = {"sc": [{"topic": "EOQ", "count": 2, "examples": ["how?"]}]}
    md = render_report(week, stats, wow, flags, topics, judged_count=3, judge_model="claude-sonnet-5", skipped=0)
    assert "Aug 9, 2026 — Aug 15, 2026" in md
    assert "Didn't work well" in md
    assert "gave_away_answer" in md
    assert "EOQ" in md


def test_flagged_note_with_newline_stays_on_one_table_row():
    week = Week(date(2026, 8, 9))
    stats = {
        "usage": {"conversations": 1, "unique_students": 1, "new_students": 0,
                  "returning_students": 1, "conversations_by_day": {"2026-08-10": 1}},
        "ratings": {"up": 0, "down": 1, "positive_rate": 0.0, "pct_turns_rated": 1.0},
        "cost": {"total_usd": 0.01, "per_conversation_usd": 0.01, "model_mix": {"claude-x": 1}},
        "content": {"rag_rate": 0.0, "rag_turns": 0, "tutor_prompt_mix": {"tutor_09": 1}},
        "per_course": {},
    }
    wow = {}
    flags = {"items": [{"id": "a", "course": "sc", "exercise": "exercise:1", "student": "u@x",
                        "source": "both", "issue_type": "gave_away_answer", "severity": "high",
                        "quote": "line one\nline two\r\nline three",
                        "one_line": "gave answer\nacross lines", "score": 12}],
             "counts_by_issue": {"gave_away_answer": 1}, "thumbs_down": 1, "judge_flagged": 0, "overlap": 0,
             "avg_score": {"avg": 12.0, "max": 40, "n": 1}}
    topics = {}
    md = render_report(week, stats, wow, flags, topics, judged_count=1, judge_model="claude-sonnet-5", skipped=0)

    table_start = md.index("| Course | Exercise | Student | Score | Issue | Severity | Note |")
    table_lines = md[table_start:].splitlines()
    # header + separator + exactly one data row for the single flagged item
    data_rows = [ln for ln in table_lines if ln.startswith("|")][2:]
    assert len(data_rows) == 1
    assert "\n" not in data_rows[0]
    assert "\r" not in data_rows[0]
    assert "gave answer across lines" in data_rows[0]


def test_report_shows_score_column_and_average():
    week = Week(date(2026, 8, 9))
    stats = {
        "usage": {"conversations": 4, "unique_students": 3, "new_students": 1,
                  "returning_students": 2, "conversations_by_day": {"2026-08-10": 4}},
        "ratings": {"up": 3, "down": 1, "positive_rate": 0.75, "pct_turns_rated": 0.5},
        "cost": {"total_usd": 0.08, "per_conversation_usd": 0.02, "model_mix": {"claude-x": 4}},
        "content": {"rag_rate": 0.5, "rag_turns": 2, "tutor_prompt_mix": {"tutor_09": 4}},
        "per_course": {},
    }
    flags = {"items": [{"id": "a", "course": "sc", "exercise": "exercise:1", "student": "u@x",
                        "source": "judge", "issue_type": "1.1.A.a", "severity": "high",
                        "quote": "gave it away", "one_line": "handed over answer", "score": 18}],
             "counts_by_issue": {"1.1.A.a": 1}, "thumbs_down": 0, "judge_flagged": 1, "overlap": 0,
             "avg_score": {"avg": 27.5, "max": 40, "n": 4}}
    topics = {"sc": [{"topic": "EOQ", "count": 1, "examples": ["how?"]}]}
    md = render_report(week, stats, {}, flags, topics, judged_count=4, judge_model="claude-sonnet-4-6", skipped=0)
    assert "| Course | Exercise | Student | Score | Issue | Severity | Note |" in md
    assert "18/40" in md                              # per-row score cell
    assert "Average rubric score: 27.5/40" in md      # Meta line
