# database_ui/analytics/topics.py
"""Aggregate per-conversation judge topics into ranked per-course lists."""
from __future__ import annotations

from collections import defaultdict

from database_ui.analytics.data import ConvRow
from database_ui.analytics.judge import Verdict


def aggregate_topics(
    convs: list[ConvRow],
    verdicts: dict[str, Verdict],
    first_question: dict[str, str],
) -> dict[str, list[dict]]:
    course_of = {c.id: c.course for c in convs}
    # course -> normalized topic -> {"display": str, "count": int, "examples": [..]}
    acc: dict[str, dict[str, dict]] = defaultdict(dict)
    for cid, verdict in verdicts.items():
        course = course_of.get(cid)
        if course is None:
            continue
        seen_norm: set[str] = set()
        for topic in verdict.topics:
            norm = topic.strip().lower()
            if not norm or norm in seen_norm:
                continue
            seen_norm.add(norm)
            bucket = acc[course].setdefault(norm, {"display": topic.strip(), "count": 0, "examples": []})
            bucket["count"] += 1
            q = first_question.get(cid)
            if q and len(bucket["examples"]) < 3 and q not in bucket["examples"]:
                bucket["examples"].append(q)
    out: dict[str, list[dict]] = {}
    for course, topics in acc.items():
        ranked = sorted(topics.values(), key=lambda b: (-b["count"], b["display"].lower()))
        out[course] = [
            {"topic": b["display"], "count": b["count"], "examples": b["examples"]}
            for b in ranked
        ]
    return out
