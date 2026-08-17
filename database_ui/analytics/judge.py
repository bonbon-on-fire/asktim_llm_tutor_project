"""LLM judge for the weekly report, behind an interface so tests never call out.

``Verdict`` captures whether a conversation worked, any issues (typed + severity
+ a supporting quote), the topics the student raised, and a one-line summary.
``transcript_hash`` lets the weekly job reuse a prior verdict when a conversation
is unchanged, keeping re-runs cheap.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

ISSUE_TYPES = ("gave_away_answer", "factual_error", "unhelpful_dead_end", "rag_grounding")
SEVERITIES = ("low", "medium", "high")


@dataclass(frozen=True)
class Verdict:
    worked_well: bool
    issues: list[dict] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    one_line: str = ""

    def as_dict(self, course: str) -> dict:
        return {
            "course": course,
            "worked_well": self.worked_well,
            "issues": self.issues,
            "topics": self.topics,
            "one_line": self.one_line,
        }


def transcript_hash(pairs: list[tuple[str, str]]) -> str:
    h = hashlib.sha256()
    for role, content in pairs:
        h.update(role.encode("utf-8"))
        h.update(b"\x00")
        h.update(content.encode("utf-8"))
        h.update(b"\x01")
    return h.hexdigest()


class Judge(Protocol):
    def judge(self, course: str, transcript: list[tuple[str, str]]) -> Verdict: ...


class FakeJudge:
    """Deterministic judge for tests. Returns ``canned[key]`` when the last
    student line matches a key, else ``default``. No network, ever."""

    def __init__(self, canned: dict[str, Verdict] | None = None, default: Verdict | None = None):
        self._canned = dict(canned or {})
        self._default = default or Verdict(worked_well=True, one_line="ok")

    def judge(self, course: str, transcript: list[tuple[str, str]]) -> Verdict:
        students = [c for r, c in transcript if r not in ("tutor", "assistant")]
        key = students[-1] if students else ""
        return self._canned.get(key, self._default)


_SYSTEM = """You are a strict evaluator of an AI tutor's conversation with a \
student. The tutor must guide via Socratic questioning and NEVER hand over a \
final/submission-ready answer. The course subject varies across many disciplines, \
so interpret the topics and any factual claims in the context of the named course. \
Given the transcript, decide whether the tutoring worked well, list concrete \
issues, and tag the 1-3 topics the student asked about.

Issue "type" must be one of: gave_away_answer, factual_error, unhelpful_dead_end, \
rag_grounding. "severity" must be one of: low, medium, high. Each issue needs a \
short verbatim "quote" from the tutor that evidences it. Keep "one_line" under 15 \
words. "topics" are short noun phrases naming the specific concepts the student \
worked on, whatever the course's subject."""


class AnthropicJudge:
    """Real judge via langchain-anthropic structured output. Not used in tests."""

    def __init__(self, model: str):
        from langchain_anthropic import ChatAnthropic  # lazy: keep tests import-clean

        self._schema = {
            "name": "verdict",
            "description": "Evaluation of one tutoring conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "worked_well": {"type": "boolean"},
                    "issues": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": list(ISSUE_TYPES)},
                                "severity": {"type": "string", "enum": list(SEVERITIES)},
                                "quote": {"type": "string"},
                            },
                            "required": ["type", "severity", "quote"],
                        },
                    },
                    "topics": {"type": "array", "items": {"type": "string"}},
                    "one_line": {"type": "string"},
                },
                "required": ["worked_well", "issues", "topics", "one_line"],
            },
        }
        # Newer Claude models (Claude 5 family) reject an explicit `temperature`,
        # so we omit it and rely on the model default rather than pinning to 0.
        self._llm = ChatAnthropic(model=model).with_structured_output(self._schema)

    def judge(self, course: str, transcript: list[tuple[str, str]]) -> Verdict:
        body = "\n\n".join(f"{role.upper()}: {content}" for role, content in transcript)
        result = self._llm.invoke(
            [("system", _SYSTEM), ("human", f"Course: {course}\n\nTranscript:\n{body}")]
        )
        return Verdict(
            worked_well=bool(result.get("worked_well", True)),
            issues=list(result.get("issues", [])),
            topics=list(result.get("topics", [])),
            one_line=str(result.get("one_line", "")),
        )
