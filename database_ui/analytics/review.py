# database_ui/analytics/review.py
"""Synthesize a short per-course "AI review" paragraph for the weekly report.

The judge grades one conversation at a time; this module steps back and writes a
single human-readable paragraph per course describing the major questions and
themes students worked on that week. It is a cheap, separate Haiku call — one
per course, not per conversation — and reuses material already produced by the
judge (first questions, one-line overviews, topics), so it adds a couple of
cents at most on top of the judge run.

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
_MAX_QUESTIONS = 40
_MAX_OVERVIEWS = 40
_MAX_TOPICS = 30

_REVIEW_SYSTEM = (
    "You write a brief weekly review of an AI tutor's conversations for one "
    "course. Given the questions students opened with, one-line summaries of how "
    "each conversation went, and the topics they touched, write ONE short "
    "paragraph (3-5 sentences) for a course instructor. Describe the major "
    "questions and themes students worked on and where they concentrated; note "
    "briefly how the tutoring went overall. Be concrete and specific to the "
    "material. Do not use bullet points, headings, or a preamble like 'This "
    "week'; just the paragraph."
)


def course_material(
    convs: list[ConvRow],
    verdicts: dict[str, Verdict],
    first_question: dict[str, str],
) -> dict[str, dict]:
    """Group the judged output by course into the raw material for a review.

    Returns ``{course: {"questions": [...], "overviews": [...], "topics": [...]}}``.
    Topics are de-duplicated (case-insensitively) per course but otherwise the
    lists preserve conversation order.
    """
    course_of = {c.id: c.course for c in convs}
    mat: dict[str, dict] = defaultdict(lambda: {"questions": [], "overviews": [], "topics": []})
    seen_topic: dict[str, set[str]] = defaultdict(set)
    for cid, verdict in verdicts.items():
        course = course_of.get(cid)
        if course is None:
            continue
        entry = mat[course]
        q = (first_question.get(cid) or "").strip()
        if q:
            entry["questions"].append(q)
        overview = (verdict.one_line or "").strip()
        if overview:
            entry["overviews"].append(overview)
        for topic in verdict.topics:
            norm = topic.strip().lower()
            if norm and norm not in seen_topic[course]:
                seen_topic[course].add(norm)
                entry["topics"].append(topic.strip())
    return dict(mat)


def _render_material(material: dict) -> str:
    """Flatten one course's material into the human message for the synthesis."""
    questions = material.get("questions", [])[:_MAX_QUESTIONS]
    overviews = material.get("overviews", [])[:_MAX_OVERVIEWS]
    topics = material.get("topics", [])[:_MAX_TOPICS]
    parts = []
    if topics:
        parts.append("Topics students worked on:\n" + ", ".join(topics))
    if questions:
        parts.append("Questions students opened with:\n"
                     + "\n".join(f"- {q}" for q in questions))
    if overviews:
        parts.append("How each conversation went (one-line summaries):\n"
                     + "\n".join(f"- {o}" for o in overviews))
    return "\n\n".join(parts)


def _default_review_fn(course: str, material: dict, model: str) -> str:
    from langchain_anthropic import ChatAnthropic  # lazy: keep tests import-clean

    llm = ChatAnthropic(model=model, temperature=0)
    body = _render_material(material)
    result = llm.invoke([
        ("system", _REVIEW_SYSTEM),
        ("human", f"Course: {course}\n\n{body}"),
    ])
    return str(getattr(result, "content", result) or "").strip()


def build_reviews(
    material_by_course: dict[str, dict],
    *,
    model: str = DEFAULT_REVIEW_MODEL,
    review_fn=None,
) -> dict[str, str]:
    """Return ``{course: paragraph}`` for every course with any material.

    Courses whose synthesis fails (or returns empty) are simply omitted, so a
    single flaky call never sinks the run or blocks the rest of the report.
    """
    fn = review_fn or _default_review_fn
    out: dict[str, str] = {}
    for course, material in material_by_course.items():
        if not any(material.get(k) for k in ("questions", "overviews", "topics")):
            continue
        try:
            text = (fn(course, material, model) or "").strip()
        except Exception as exc:  # noqa: BLE001 - one bad course must not sink the report
            print(f"review skipped {course}: {type(exc).__name__}: {exc}")
            continue
        if text:
            out[course] = text
    return out
