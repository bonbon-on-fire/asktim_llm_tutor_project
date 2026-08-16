# database_ui/analytics/examples.py
"""Select example conversations (exemplary / high-engagement / random sample).

The random sample is seeded by the week key so a regenerated cache is identical.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict

from database_ui.analytics.data import ConvRow, MsgRow
from database_ui.analytics.judge import Verdict

_EXEMPLARY_CAP = 5
_ENGAGEMENT_CAP = 5


def pick_examples(
    convs: list[ConvRow],
    msgs: list[MsgRow],
    verdicts: dict[str, Verdict],
    *,
    seed: str,
    per_course: int = 2,
) -> dict:
    counts: Counter = Counter(m.conversation_id for m in msgs)
    up_rated = {m.conversation_id for m in msgs if m.rating == 1}
    conv_ids = [c.id for c in convs]

    def by_messages(ids):
        return sorted(ids, key=lambda cid: (-counts.get(cid, 0), cid))

    exemplary = by_messages([
        cid for cid in conv_ids
        if verdicts.get(cid, Verdict(True)).worked_well and cid in up_rated
    ])[:_EXEMPLARY_CAP]

    high_engagement = by_messages(conv_ids)[:_ENGAGEMENT_CAP]

    by_course: dict[str, list[str]] = defaultdict(list)
    for c in convs:
        by_course[c.course].append(c.id)
    rng = random.Random(seed)
    sample: dict[str, list[str]] = {}
    for course, ids in sorted(by_course.items()):
        pool = sorted(ids)
        rng.shuffle(pool)
        sample[course] = sorted(pool[:per_course])

    return {"exemplary": exemplary, "high_engagement": high_engagement, "sample": sample}
