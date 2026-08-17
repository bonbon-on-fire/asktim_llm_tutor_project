"""Adapt the mature rubric_08 judge to the weekly report's ``Verdict`` interface.

The rubric judge (``eval.tutor_judge.run_judge.grade_transcript_payload``) grades a
conversation against a 40-point rubric and returns a rich ``grade`` dict. This
adapter converts the weekly ``(role, content)`` transcript into the judge's
``exchanges`` shape, runs the judge, extracts ``topics`` via a separate cheap call
(the rubric judge emits none), and maps the grade into a ``Verdict``: ``worked_well``
from the score threshold, ``issues`` from rubric deductions, ``one_line`` from the
overview, and the full grade preserved in ``Verdict.grade`` for the cache.

Text-only v1: ``course`` is passed empty to the judge so figure discovery is
skipped; the course display name is passed as ``context``.
"""
from __future__ import annotations

from .judge import Verdict

# A conversation "worked well" iff it scores at least 80% of the 40-point rubric.
SCORE_THRESHOLD = 32
# rubric_08 is calibrated on sonnet-4-6, and the judge hardcodes temperature=0
# (Claude-5 models 400 on that param), so pin the judge model here.
DEFAULT_JUDGE_MODEL = "claude-sonnet-4-6"
# Topics are a cheap, separate extraction — Haiku is plenty.
DEFAULT_TOPICS_MODEL = "claude-haiku-4-5-20251001"

_TUTOR_ROLES = ("tutor", "assistant")

_TOPICS_SYSTEM = (
    "You extract the 1-3 topics a student worked on in a tutoring conversation. "
    "Return short noun phrases naming the specific concepts the student asked "
    "about, whatever the course's subject. Do not judge the tutoring."
)


def pairs_to_exchanges(transcript: list[tuple[str, str]]) -> list[dict]:
    """Pair each student turn with the tutor turn that answers it.

    ``[("student","q1"),("tutor","a1"),("student","q2"),("assistant","a2")]``
    -> ``[{"student":"q1","tutor":"a1"},{"student":"q2","tutor":"a2"}]``.
    A leading tutor turn yields ``student=""``; a trailing student turn yields
    ``tutor=""`` — the judge tolerates both and needs a non-empty list.
    """
    exchanges: list[dict] = []
    pending: dict | None = None
    for role, content in transcript:
        if role in _TUTOR_ROLES:
            if pending is None:
                pending = {"student": ""}
            pending["tutor"] = content
            exchanges.append(pending)
            pending = None
        else:
            if pending is not None:
                pending.setdefault("tutor", "")
                exchanges.append(pending)
            pending = {"student": content}
    if pending is not None:
        pending.setdefault("tutor", "")
        exchanges.append(pending)
    return exchanges


def _severity(points: float) -> str:
    if points >= 5:
        return "high"
    if points >= 2:
        return "medium"
    return "low"


def _grade_to_issues(grade: dict) -> list[dict]:
    """Flatten rubric deductions into weekly ``issues``, worst (most points) first."""
    issues: list[dict] = []
    sections = grade.get("sections") or {}
    for section in sections.values():
        if not isinstance(section, dict):
            continue
        criteria = section.get("criteria") or {}
        for crit in criteria.values():
            if not isinstance(crit, dict):
                continue
            for d in crit.get("deductions") or []:
                if not isinstance(d, dict):
                    continue
                points = d.get("points", 0) or 0
                issues.append(
                    {
                        "type": str(d.get("sub_criterion_id", "")),
                        "severity": _severity(points),
                        "quote": str(d.get("reason", "")),
                        "points": points,
                    }
                )
    issues.sort(key=lambda i: i["points"], reverse=True)
    return issues


def grade_to_verdict(grade: dict, topics: list[str] | None = None) -> Verdict:
    """Map a rubric grade payload into a weekly ``Verdict`` (full grade retained)."""
    total = grade.get("total_score", 0) or 0
    return Verdict(
        worked_well=total >= SCORE_THRESHOLD,
        issues=_grade_to_issues(grade),
        topics=list(topics or []),
        one_line=str(grade.get("overview", "")),
        grade=grade,
    )


def _default_grade_fn(payload: dict, model: str) -> dict:
    from eval.tutor_judge.run_judge import grade_transcript_payload  # lazy: keep tests import-clean

    return grade_transcript_payload(payload, model_name=model)


def _default_topics_fn(course: str, transcript: list[tuple[str, str]], model: str) -> list[str]:
    from langchain_anthropic import ChatAnthropic  # lazy: keep tests import-clean

    schema = {
        "name": "topics",
        "description": "The 1-3 topics the student worked on.",
        "parameters": {
            "type": "object",
            "properties": {"topics": {"type": "array", "items": {"type": "string"}}},
            "required": ["topics"],
        },
    }
    llm = ChatAnthropic(model=model).with_structured_output(schema)
    body = "\n\n".join(f"{role.upper()}: {content}" for role, content in transcript)
    result = llm.invoke([("system", _TOPICS_SYSTEM), ("human", f"Course: {course}\n\nTranscript:\n{body}")])
    return [str(t) for t in (result.get("topics", []) or [])]


class RubricJudge:
    """Weekly-report judge backed by the mature rubric_08 grader.

    ``grade_fn`` / ``topics_fn`` are injection seams: tests pass fakes so no network
    call happens. In production they default to the real rubric judge and a Haiku
    topics extraction.
    """

    def __init__(
        self,
        model: str = DEFAULT_JUDGE_MODEL,
        *,
        topics_model: str = DEFAULT_TOPICS_MODEL,
        grade_fn=None,
        topics_fn=None,
    ):
        self._model = model
        self._topics_model = topics_model
        self._grade_fn = grade_fn or _default_grade_fn
        self._topics_fn = topics_fn or _default_topics_fn

    def judge(self, course: str, transcript: list[tuple[str, str]], *, exercise: str = "") -> Verdict:
        payload = {
            "course": "",           # text-only v1: disable figure discovery
            "context": course,      # course display name informs the judge
            "exercise": exercise,
            "exchanges": pairs_to_exchanges(transcript),
        }
        grade = self._grade_fn(payload, self._model)
        topics = self._topics_fn(course, transcript, self._topics_model)
        return grade_to_verdict(grade, topics)
