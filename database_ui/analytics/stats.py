"""Pure descriptive statistics for the weekly report (sections 1-4, 8, 9).

Input is the plain dataclasses from ``data.py``; output is a JSON-serializable
dict. No DB, no I/O -> fully unit-testable. Cost leans on ``cost_usd`` (always
present on tutor rows); token totals are a best-effort parse of ``usage_json``.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from database_ui.analytics.data import ConvRow, MsgRow
from ui_core.usage import model_from_usage_json, new_tokens_from_usage_json

# Tutor turns carry rating/cost; student turns don't. Accept both historical labels.
TUTOR_ROLES = {"tutor", "assistant"}


def is_tutor(role: str) -> bool:
    return role in TUTOR_ROLES


def _round(x: float, n: int = 4) -> float:
    return round(float(x), n)


def _section(convs: list[ConvRow], msgs: list[MsgRow], returning: set[str]) -> dict:
    tutor_msgs = [m for m in msgs if is_tutor(m.role)]
    students = {c.username for c in convs if c.username}
    ret = len(students & returning)
    durations = [
        (c.last_active_at - c.started_at).total_seconds()
        for c in convs
        if c.started_at and c.last_active_at
    ]
    by_day: Counter = Counter(
        c.started_at.date().isoformat() for c in convs if c.started_at
    )
    msgs_by_day: Counter = Counter(
        m.created_at.date().isoformat() for m in msgs if m.created_at
    )
    per_conv_msgs: Counter = Counter(m.conversation_id for m in msgs)
    up = sum(1 for m in tutor_msgs if m.rating == 1)
    down = sum(1 for m in tutor_msgs if m.rating == -1)
    rated = up + down
    rag_turns = sum(1 for m in tutor_msgs if m.has_rag)
    costs = [m.cost_usd or 0.0 for m in tutor_msgs]
    models: Counter = Counter(
        model_from_usage_json(m.usage_json) or "unknown" for m in tutor_msgs
    )
    ex_kinds: Counter = Counter(c.exercise_kind for c in convs)
    exercises: Counter = Counter(f"{c.exercise_kind}:{c.exercise_number}" for c in convs)
    prompts: Counter = Counter(c.tutor_prompt for c in convs)

    return {
        "usage": {
            "conversations": len(convs),
            "unique_students": len(students),
            "returning_students": ret,
            "new_students": len(students) - ret,
            "total_messages": len(msgs),
            "student_messages": len(msgs) - len(tutor_msgs),
            "tutor_messages": len(tutor_msgs),
            "avg_messages_per_conversation": _round(
                sum(per_conv_msgs.values()) / len(convs) if convs else 0.0, 2
            ),
            "avg_duration_seconds": _round(
                sum(durations) / len(durations) if durations else 0.0, 1
            ),
            "short_conversations": sum(1 for c in per_conv_msgs.values() if c <= 2),
            "conversations_by_day": dict(sorted(by_day.items())),
            "messages_by_day": dict(sorted(msgs_by_day.items())),
        },
        "ratings": {
            "up": up,
            "down": down,
            "rated_turns": rated,
            "positive_rate": _round(up / rated, 4) if rated else 0.0,
            "pct_turns_rated": _round(rated / len(tutor_msgs), 4) if tutor_msgs else 0.0,
        },
        "cost": {
            "total_usd": _round(sum(costs), 4),
            "per_conversation_usd": _round(sum(costs) / len(convs), 4) if convs else 0.0,
            "tokens": sum(new_tokens_from_usage_json(m.usage_json) for m in tutor_msgs),
            "model_mix": dict(models),
        },
        "content": {
            "exercise_kind_split": dict(ex_kinds),
            "top_exercises": dict(exercises.most_common(10)),
            "focus_problem_conversations": sum(1 for c in convs if c.focus_problem is not None),
            "rag_turns": rag_turns,
            "rag_rate": _round(rag_turns / len(tutor_msgs), 4) if tutor_msgs else 0.0,
            "tutor_prompt_mix": dict(prompts),
        },
    }


def compute_stats(convs: list[ConvRow], msgs: list[MsgRow], returning: set[str]) -> dict:
    """Overall stats plus a per-course breakdown."""
    overall = _section(convs, msgs, returning)
    ids_by_course: dict[str, set[str]] = defaultdict(set)
    for c in convs:
        ids_by_course[c.course].add(c.id)
    per_course = {}
    for course, ids in sorted(ids_by_course.items()):
        c_convs = [c for c in convs if c.course == course]
        c_msgs = [m for m in msgs if m.conversation_id in ids]
        per_course[course] = _section(c_convs, c_msgs, returning)
    overall["per_course"] = per_course
    return overall


_HEADLINE = [
    ("conversations", ("usage", "conversations")),
    ("total_messages", ("usage", "total_messages")),
    ("unique_students", ("usage", "unique_students")),
    ("new_students", ("usage", "new_students")),
    ("cost_usd", ("cost", "total_usd")),
    ("positive_rate", ("ratings", "positive_rate")),
    ("rag_rate", ("content", "rag_rate")),
]


def _dig(d: dict, path: tuple[str, str]):
    return d.get(path[0], {}).get(path[1], 0)


def week_over_week(current: dict, prior: dict) -> dict:
    """Arrow + delta on headline metrics vs the prior week."""
    out = {}
    for name, path in _HEADLINE:
        cur, pri = _dig(current, path), _dig(prior, path)
        arrow = "▲" if cur > pri else "▼" if cur < pri else "–"
        out[name] = {"current": cur, "prior": pri, "delta": _round(cur - pri, 4), "arrow": arrow}
    return out
