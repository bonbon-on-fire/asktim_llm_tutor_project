# database_ui/analytics/report.py
"""Render the weekly report Markdown (PR body + committed report.md). Text only."""
from __future__ import annotations

from database_ui.analytics.weeks import Week
from database_ui.courses import course_display_name


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def render_report(week: Week, stats: dict, wow: dict, flags: dict, topics_by_course: dict,
                  *, judged_count: int, judge_model: str, skipped: int) -> str:
    u, r, c, ct = stats["usage"], stats["ratings"], stats["cost"], stats["content"]
    lines: list[str] = []
    lines.append(f"# Weekly report — {week.label()}")
    lines.append("")

    def arrow(name: str) -> str:
        return wow.get(name, {}).get("arrow", "")

    lines.append("## Overview")
    lines.append("")
    lines.append(f"- **Conversations:** {u['conversations']} {arrow('conversations')}")
    lines.append(f"- **Students:** {u['unique_students']} {arrow('unique_students')} "
                 f"({u['new_students']} new, {u['returning_students']} returning)")
    lines.append(f"- **Positive rating:** {_pct(r['positive_rate'])} {arrow('positive_rate')} "
                 f"({r['up']}👍 / {r['down']}👎, {_pct(r['pct_turns_rated'])} of turns rated)")
    lines.append(f"- **Cost:** ${c['total_usd']:.2f} {arrow('cost_usd')} "
                 f"(${c['per_conversation_usd']:.3f}/conversation)")
    lines.append(f"- **RAG rate:** {_pct(ct['rag_rate'])} {arrow('rag_rate')}")
    lines.append("")

    lines.append("## 🚩 Didn't work well")
    lines.append("")
    lines.append(f"{len(flags['items'])} flagged — {flags['thumbs_down']}👎 + "
                 f"{flags['judge_flagged']} judge ({flags['overlap']} overlap).")
    lines.append("")
    if flags["items"]:
        lines.append("| Course | Exercise | Student | Score | Issue | Severity | Note |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        score_max = (flags.get("avg_score") or {}).get("max", 40)
        for i in flags["items"][:25]:
            note = (i["one_line"] or i["quote"]).replace("\n", " ").replace("\r", " ")
            note = note.replace("|", "\\|")[:80]
            score = i.get("score")
            score_cell = f"{score}/{score_max}" if score is not None else "—"
            lines.append(f"| {course_display_name(i['course'])} | {i['exercise']} | "
                         f"{i['student']} | {score_cell} | {i['issue_type']} | {i['severity']} | {note} |")
    lines.append("")

    lines.append("## 🗣 Top topics")
    lines.append("")
    for course, rows in sorted(topics_by_course.items()):
        top = " · ".join(f"{t['topic']} ({t['count']})" for t in rows[:8])
        lines.append(f"- **{course_display_name(course)}:** {top}")
    lines.append("")

    lines.append("## Meta")
    lines.append("")
    lines.append(f"- Judged {judged_count} conversations with `{judge_model}`"
                 + (f" ({skipped} skipped)" if skipped else "") + ".")
    avg = flags.get("avg_score") or {}
    if avg.get("n"):
        lines.append(f"- Average rubric score: {avg['avg']:.1f}/{avg['max']} (over {avg['n']} graded).")
    lines.append(f"- Model mix: {', '.join(f'{m} ({n})' for m, n in c['model_mix'].items())}")
    lines.append("")
    return "\n".join(lines)
