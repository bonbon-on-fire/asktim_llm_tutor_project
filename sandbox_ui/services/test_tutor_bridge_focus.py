"""Focus directive wiring in the sandbox tutor bridge.

Run:
    python -m sandbox_ui.services.test_tutor_bridge_focus
"""
from __future__ import annotations

from sandbox_ui.services.tutor_bridge import build_assignment_text
from utils.curriculum import list_subproblems, subproblem_label

COURSE = "supply_chain_design"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    subs = list_subproblems(COURSE, "1", "practice")
    if not subs:
        print("SKIP - no sub-problems for", COURSE, "practice 1")
        return 0
    n = subs[-1][0]

    base = build_assignment_text(COURSE, "1", exercise_kind="practice")
    focused = build_assignment_text(COURSE, "1", exercise_kind="practice", focus_problem=n)

    label = subproblem_label(COURSE, "1", "practice", n)
    ok &= _check("focus directive present", "Focus: the student is currently working on" in focused)
    ok &= _check("focus names the sub-problem label", label and label in focused, label)
    ok &= _check("no-focus output byte-identical to today",
                 build_assignment_text(COURSE, "1", exercise_kind="practice") == base)
    ok &= _check("focus differs from no-focus", focused != base)
    # Directive sits immediately before the Exercise block.
    ok &= _check("directive precedes Exercise block",
                 focused.index("Focus: the student is currently working on") < focused.index("Exercise:\n"))

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
