"""Provider-neutral assembly of the cache-friendly interleaved message plan.

The plan is a list of (role, content) steps that each provider sender converts
to its own message shape. Roles: 'system_static' (leading system prompt),
'student', 'rag' (a system-channel retrieval block), 'tutor' (verbatim JSON).

Byte-stability matters: every replayed rag/tutor block must be identical across
turns of a conversation or prompt caching misses. tutor_output_json produces a
canonical, deterministic string from the two stored fields.
"""
from __future__ import annotations

import json


def tutor_output_json(reasoning: str | None, answer: str | None) -> str:
    """Canonical verbatim tutor output: the two-field JSON, fixed key order."""
    return json.dumps(
        {
            "pedagogical-reasoning": reasoning or "",
            "Student-facing-answer": answer or "",
        },
        ensure_ascii=False,
    )


def build_message_plan(
    *,
    static_system: str,
    prior_turns: list[dict],
    current_student: str,
    current_rag: str,
) -> list[tuple[str, str]]:
    """Ordered (role, content) plan: system, then per prior turn
    student -> [rag] -> tutor, then the current student -> [rag]. RAG steps with
    empty text are omitted (non-rag mode / no retrieval)."""
    plan: list[tuple[str, str]] = [("system_static", static_system)]
    for t in prior_turns:
        plan.append(("student", t["student_content"]))
        if t.get("rag_text"):
            plan.append(("rag", t["rag_text"]))
        plan.append(("tutor", t["tutor_json"]))
    plan.append(("student", current_student))
    if current_rag:
        plan.append(("rag", current_rag))
    return plan
