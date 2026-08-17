# database_ui/analytics/flags.py
"""Combine thumbs-down and judge verdicts into the ranked 'didn't work well' list."""
from __future__ import annotations

from collections import Counter

from database_ui.analytics.data import ConvRow, MsgRow
from database_ui.analytics.judge import Verdict

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "": 3}
_SOURCE_RANK = {"both": 0, "judge": 1, "thumb": 2}


def build_flags(convs: list[ConvRow], msgs: list[MsgRow], verdicts: dict[str, Verdict]) -> dict:
    conv_by_id = {c.id: c for c in convs}
    thumbed = {m.conversation_id for m in msgs if m.rating == -1}
    judged_bad = {cid for cid, v in verdicts.items() if not v.worked_well}
    flagged = thumbed | judged_bad

    items = []
    counts: Counter = Counter()
    for cid in flagged:
        conv = conv_by_id.get(cid)
        if conv is None:
            continue
        verdict = verdicts.get(cid)
        grade = verdict.grade if (verdict and verdict.grade) else None
        score = grade.get("total_score") if grade else None
        by_judge = cid in judged_bad
        by_thumb = cid in thumbed
        source = "both" if by_judge and by_thumb else "judge" if by_judge else "thumb"
        top_issue = verdict.issues[0] if (verdict and verdict.issues) else {}
        issue_type = top_issue.get("type", "thumbs_down" if not by_judge else "unspecified")
        severity = top_issue.get("severity", "medium" if by_judge else "low")
        counts[issue_type] += 1
        items.append({
            "id": cid,
            "course": conv.course,
            "exercise": f"{conv.exercise_kind}:{conv.exercise_number}",
            "student": conv.username,
            "score": score,
            "source": source,
            "issue_type": issue_type,
            "severity": severity,
            "quote": top_issue.get("quote", ""),
            "one_line": verdict.one_line if verdict else "",
        })

    items.sort(key=lambda i: (_SEVERITY_RANK.get(i["severity"], 3), _SOURCE_RANK[i["source"]], i["id"]))

    graded = [
        v.grade["total_score"] for v in verdicts.values()
        if v.grade and isinstance(v.grade.get("total_score"), (int, float))
    ]
    if graded:
        maxes = [v.grade.get("max_score", 40) for v in verdicts.values() if v.grade]
        avg_score = {"avg": sum(graded) / len(graded), "max": maxes[0] if maxes else 40, "n": len(graded)}
    else:
        avg_score = {"avg": 0.0, "max": 40, "n": 0}

    return {
        "items": items,
        "avg_score": avg_score,
        "counts_by_issue": dict(counts),
        "thumbs_down": len(thumbed),
        "judge_flagged": len(judged_bad),
        "overlap": len(thumbed & judged_bad),
    }
