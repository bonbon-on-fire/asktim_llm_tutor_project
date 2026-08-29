# database_ui/analytics/review.py
"""Synthesize short "AI review" paragraphs for the weekly report.

The judge grades one conversation at a time; this module steps back and writes a
short human-readable paragraph per *content week* — each course's conversations
are split by the assignment (Practice #) they belong to, and each Practice #
gets its own paragraph. Content weeks stay open once released, so a single
calendar week's conversations span several Practice #s at once; keeping the
review split by Practice # attributes each observation to the right content
week instead of blending them.

It is a cheap, separate Haiku call — one per (course, Practice #), not per
conversation — and reuses material already produced by the judge (first
questions, one-line overviews, topics), so it adds a couple of cents at most on
top of the judge run.

``review_fn`` is an injection seam: tests pass a fake so no network call happens;
production defaults to a real Haiku call.
"""

from __future__ import annotations

from collections import defaultdict

from database_ui.analytics.data import ConvRow
from database_ui.analytics.judge import Verdict

# Haiku is plenty for a short narrative synthesis of already-judged material.
DEFAULT_REVIEW_MODEL = "claude-haiku-4-5-20251001"

# Keep each course's material bounded so the synthesis stays cheap regardless of
# how busy a week was; the newest/first entries are representative enough.
_MAX_OVERVIEWS = 40
_MAX_TOPICS = 30

_REVIEW_SYSTEM = (
    "You write a brief weekly review of an AI tutor's conversations for a "
    "single assignment within one course. You are given one-line summaries of "
    "how each conversation went and the topics students covered for that one "
    "assignment. Write ONE plain paragraph for a course instructor that "
    "summarizes the kinds of conversations students had on this assignment and "
    "the main topics they focused on, and calls out the common areas of "
    "confusion or difficulty students ran into. Use only as many sentences as "
    "the material genuinely warrants and no more than five — a quiet assignment "
    "with little activity may need just one or two. Do not pad, speculate, or "
    "restate the same point to reach a length; if there is little to say, say "
    "little. Be concrete and specific to the material. Do not name the course "
    "or the assignment, or refer to 'this assignment'; the reader already sees "
    "the assignment heading, so write about the students and their work "
    "directly. Do not use bullet points, headings, or a preamble like 'This "
    "week'; just the paragraph."
)


def practice_label(kind: str | None, number: str | None) -> str:
    """Human label for a content week, matching the dashboard's ``flagLabel``.

    ``"Practice 7"`` when the assignment is a practice, ``"Exercise 3"``
    otherwise; a blank/missing number has no content week to attribute to and
    falls into the ``"Unspecified"`` bucket.
    """
    num = ("" if number is None else str(number)).strip()
    if not num:
        return "Unspecified"
    word = "Practice" if kind == "practice" else "Exercise"
    return f"{word} {num}"


def _practice_sort_key(number: str | None):
    """Order content weeks numerically, then lexically; ``Unspecified`` last.

    Mirrors ``services.conversations._assignment_sort_key`` so the review's
    Practice order matches the assignment order shown elsewhere in the UI.
    """
    try:
        return (0, float(number), "")  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return (1, 0.0, "" if number is None else str(number))


def course_material(
    convs: list[ConvRow],
    verdicts: dict[str, Verdict],
    first_question: dict[str, str],
) -> dict[str, dict]:
    """Group the judged output by course and content week (Practice #).

    Returns ``{course: {practice_label: {"questions", "overviews", "topics"}}}``.
    Within a course the Practice #s are ordered numerically then lexically (the
    ``"Unspecified"`` bucket for conversations with no assignment number sorts
    last), matching the assignment order shown elsewhere in the UI. Topics are
    de-duplicated (case-insensitively) within each ``(course, practice)`` but
    otherwise the lists preserve conversation order.
    """
    conv_of = {c.id: c for c in convs}
    # course -> practice_label -> material
    mat: dict[str, dict[str, dict]] = defaultdict(
        lambda: defaultdict(lambda: {"questions": [], "overviews": [], "topics": []})
    )
    seen_topic: dict[tuple[str, str], set[str]] = defaultdict(set)
    sort_of: dict[tuple[str, str], tuple] = {}
    for cid, verdict in verdicts.items():
        conv = conv_of.get(cid)
        if conv is None:
            continue
        course = conv.course
        label = practice_label(conv.exercise_kind, conv.exercise_number)
        sort_of[(course, label)] = _practice_sort_key(conv.exercise_number)
        entry = mat[course][label]
        q = (first_question.get(cid) or "").strip()
        if q:
            entry["questions"].append(q)
        overview = (verdict.one_line or "").strip()
        if overview:
            entry["overviews"].append(overview)
        for topic in verdict.topics:
            norm = topic.strip().lower()
            if norm and norm not in seen_topic[(course, label)]:
                seen_topic[(course, label)].add(norm)
                entry["topics"].append(topic.strip())
    # Emit each course's practices in assignment order.
    out: dict[str, dict] = {}
    for course, by_label in mat.items():
        ordered = sorted(by_label, key=lambda lb: sort_of[(course, lb)])
        out[course] = {lb: by_label[lb] for lb in ordered}
    return out


def _render_material(material: dict) -> str:
    """Flatten one course's material into the human message for the synthesis."""
    overviews = material.get("overviews", [])[:_MAX_OVERVIEWS]
    topics = material.get("topics", [])[:_MAX_TOPICS]
    parts = []
    if topics:
        parts.append("Topics students worked on:\n" + ", ".join(topics))
    if overviews:
        parts.append(
            "How each conversation went (one-line summaries):\n"
            + "\n".join(f"- {o}" for o in overviews)
        )
    return "\n\n".join(parts)


def _default_review_fn(course: str, label: str, material: dict, model: str) -> str:
    from langchain_anthropic import ChatAnthropic  # lazy: keep tests import-clean

    llm = ChatAnthropic(model=model, temperature=0)
    body = _render_material(material)
    result = llm.invoke(
        [
            ("system", _REVIEW_SYSTEM),
            ("human", f"Course: {course}\nAssignment: {label}\n\n{body}"),
        ]
    )
    return str(getattr(result, "content", result) or "").strip()


def build_reviews(
    material_by_course: dict[str, dict],
    *,
    model: str = DEFAULT_REVIEW_MODEL,
    review_fn=None,
) -> dict[str, list[dict]]:
    """Return ``{course: [{"label", "text"}, ...]}`` — one paragraph per Practice #.

    ``material_by_course`` is the nested output of :func:`course_material`. Each
    ``(course, practice)`` with any material becomes one short section, emitted
    in the Practice order the material already carries. A practice whose
    synthesis fails (or returns empty) is dropped; a course left with no
    sections is omitted entirely, so a single flaky call never sinks the run or
    blocks the rest of the report.
    """
    fn = review_fn or _default_review_fn
    out: dict[str, list[dict]] = {}
    for course, by_label in material_by_course.items():
        sections: list[dict] = []
        for label, material in by_label.items():
            if not any(material.get(k) for k in ("questions", "overviews", "topics")):
                continue
            try:
                text = (fn(course, label, material, model) or "").strip()
            except (
                Exception
            ) as exc:  # noqa: BLE001 - one bad practice must not sink the report
                print(f"review skipped {course}/{label}: {type(exc).__name__}: {exc}")
                continue
            if text:
                sections.append({"label": label, "text": text})
        if sections:
            out[course] = sections
    return out
