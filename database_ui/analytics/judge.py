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
    grade: dict | None = None

    def as_dict(self, course: str) -> dict:
        out = {
            "course": course,
            "worked_well": self.worked_well,
            "issues": self.issues,
            "topics": self.topics,
            "one_line": self.one_line,
        }
        if self.grade is not None:
            out["grade"] = self.grade
        return out


def transcript_hash(pairs: list[tuple[str, str]]) -> str:
    h = hashlib.sha256()
    for role, content in pairs:
        h.update(role.encode("utf-8"))
        h.update(b"\x00")
        h.update(content.encode("utf-8"))
        h.update(b"\x01")
    return h.hexdigest()


class Judge(Protocol):
    def judge(self, course: str, transcript: list[tuple[str, str]], *, exercise: str = "") -> Verdict: ...


class FakeJudge:
    """Deterministic judge for tests. Returns ``canned[key]`` when the last
    student line matches a key, else ``default``. No network, ever."""

    def __init__(self, canned: dict[str, Verdict] | None = None, default: Verdict | None = None):
        self._canned = dict(canned or {})
        self._default = default or Verdict(worked_well=True, one_line="ok")

    def judge(self, course: str, transcript: list[tuple[str, str]], *, exercise: str = "") -> Verdict:
        students = [c for r, c in transcript if r not in ("tutor", "assistant")]
        key = students[-1] if students else ""
        return self._canned.get(key, self._default)
