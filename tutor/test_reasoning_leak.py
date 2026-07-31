r"""Regression tests: pedagogical-reasoning / envelope leakage into the student reply.

Two failure modes observed in the beta-plus DB (supply_chain_design ex7, 2026-07-27..30):

- Mode A — the whole ``{"pedagogical-reasoning":...,"Student-facing-answer":...}``
  envelope is dumped as the student reply when the model's JSON is invalid, so the
  hidden reasoning is shown verbatim. Root cause: the ``(answer or content)``
  fallback in ``_normalize_tutor_ai_message`` used the raw model text as the answer.

- Mode B — valid JSON, but the ``Student-facing-answer`` value ends with
  hallucinated tool-invoke closing tags (``</Student-facing-answer>``,
  ``</invoke>``, ``</parameter>``) that leak into the rendered reply.

These lock in that neither the hidden reasoning nor the envelope scaffolding ever
reaches the student.

Run:
    python -m tutor.test_reasoning_leak
"""

import json

from langchain_core.messages import AIMessage

from tutor.run_tutor import _normalize_tutor_ai_message, parse_tutor_response


# --- Mode B: trailing tool-invoke tags inside a valid-JSON answer ------------

def test_strips_trailing_invoke_tags_from_answer():
    raw = (
        '{"pedagogical-reasoning":"nudge them toward the demand constraint",'
        '"Student-facing-answer":"Which problem are you working on?'
        '</Student-facing-answer>\\n</invoke>"}'
    )
    reasoning, answer = parse_tutor_response(raw)
    assert answer == "Which problem are you working on?", repr(answer)
    assert "</invoke>" not in answer
    assert "Student-facing-answer" not in answer
    # the hidden reasoning is still recovered for the DB column, not shown
    assert reasoning == "nudge them toward the demand constraint"


def test_strips_trailing_parameter_tag_from_answer():
    raw = '{"pedagogical-reasoning":"r","Student-facing-answer":"Answer text.</parameter>"}'
    _, answer = parse_tutor_response(raw)
    assert answer == "Answer text.", repr(answer)


def test_clean_answer_is_untouched():
    raw = '{"pedagogical-reasoning":"r","Student-facing-answer":"Good — what is i?"}'
    _, answer = parse_tutor_response(raw)
    assert answer == "Good — what is i?", repr(answer)


# --- Mode A: invalid JSON must never dump the reasoning to the student -------

def test_broken_envelope_does_not_leak_reasoning():
    # Unterminated JSON (a real shape from the DB): json.loads fails, so before the
    # fix the whole string — reasoning included — became the student answer.
    broken = (
        '{"pedagogical-reasoning": "SECRET plan: the student is stuck, I will '
        'nudge them", "Student-facing-answer": "Good, think about it this way'
    )
    msg = _normalize_tutor_ai_message(AIMessage(content=broken))
    payload = json.loads(msg.content)
    ans = payload["Student-facing-answer"]
    assert "SECRET plan" not in ans, ans
    assert "pedagogical-reasoning" not in ans, ans
    # falls back to the canned recovery message rather than raw JSON
    assert "could not generate a valid response" in ans.lower(), ans


def test_nested_envelope_answer_does_not_leak():
    # Valid outer JSON whose answer value is *itself* a raw envelope (double-encode).
    inner = '{"pedagogical-reasoning":"HIDDEN","Student-facing-answer":"real reply"}'
    raw = json.dumps({"pedagogical-reasoning": "r", "Student-facing-answer": inner})
    _, answer = parse_tutor_response(raw)
    assert "HIDDEN" not in (answer or ""), repr(answer)
    assert "pedagogical-reasoning" not in (answer or ""), repr(answer)


def test_plain_prose_passthrough_still_works():
    # Model returned bare prose (no JSON envelope at all): still shown as-is.
    msg = _normalize_tutor_ai_message(AIMessage(content="Just try isolating x first."))
    payload = json.loads(msg.content)
    assert payload["Student-facing-answer"] == "Just try isolating x first."


if __name__ == "__main__":
    test_strips_trailing_invoke_tags_from_answer()
    test_strips_trailing_parameter_tag_from_answer()
    test_clean_answer_is_untouched()
    test_broken_envelope_does_not_leak_reasoning()
    test_nested_envelope_answer_does_not_leak()
    test_plain_prose_passthrough_still_works()
    print("PASS - no reasoning/envelope leakage into student reply")
