"""Standalone: per-conversation new-token sum over stored usage_json.

Run:
    python -m main_ui.services.test_conversation_tokens
"""
from __future__ import annotations

import json
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from main_ui.db.models import Base
from main_ui.services import conversation as svc
from ui_core.usage import new_tokens_from_usage_json


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def _usage(**calls) -> str:
    return json.dumps({"usd": 0.0, "calls": calls})


def main() -> int:
    ok = True
    # Pure parser: new = max(0, input-cache_read)+output, summed across calls.
    u = _usage(
        tutor={"input_tokens": 30000, "output_tokens": 300, "cache_read": 28000},
        student={"input_tokens": 1000, "output_tokens": 20, "cache_read": 900},
    )
    ok &= _check("parser sums new tokens", new_tokens_from_usage_json(u) == (2000 + 300) + (100 + 20),
                 new_tokens_from_usage_json(u))
    ok &= _check("parser null -> 0", new_tokens_from_usage_json(None) == 0)
    ok &= _check("parser malformed -> 0", new_tokens_from_usage_json("{not json") == 0)
    ok &= _check("parser missing keys -> 0", new_tokens_from_usage_json(json.dumps({"calls": {"t": {}}})) == 0)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        convo = svc.find_or_create_conversation(
            s, session_id="a", conversation_id=None, course="supply_chain_design",
            exercise_number="7", exercise_kind="practice", tutor_prompt="tutor_07",
        )
        s.commit()
        # Two completed turns with known new-token contributions. The turn number
        # for `complete_exchange_tutor` must match the student row's own `.turn`
        # (both halves of a turn share one turn number, see `append_exchange`);
        # `start_exchange_student_only` returns that student row, so we read
        # `.turn` off of it rather than recomputing it separately.
        for text, tokens in (("q1", 2300), ("q2", 4000)):
            student_msg = svc.start_exchange_student_only(s, conversation=convo, student_text=text)
            svc.complete_exchange_tutor(
                s, conversation=convo, turn=student_msg.turn,
                tutor_text="a", pedagogical_reasoning=None,
                usage_json=_usage(tutor={"input_tokens": tokens, "output_tokens": 0, "cache_read": 0}),
            )
        s.commit()
        total = svc.sum_conversation_new_tokens(s, convo)
        ok &= _check("conversation sum across turns", total == 2300 + 4000, total)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
