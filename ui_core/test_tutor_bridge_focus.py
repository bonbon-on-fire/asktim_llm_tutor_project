"""Focus-directive + cache-key checks for the tutor bridge.

Run:
    python -m ui_core.test_tutor_bridge_focus
"""
from __future__ import annotations

from ui_core.tutor_bridge import TutorBridge

COURSE = "supply_chain_design"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    b = TutorBridge()

    base = b.build_assignment_text(COURSE, "1", exercise_kind="practice", context_mode="full_context")
    focused = b.build_assignment_text(
        COURSE, "1", exercise_kind="practice", context_mode="full_context", focus_problem=2
    )

    ok &= _check("no focus_problem -> unchanged text",
                 b.build_assignment_text(COURSE, "1", exercise_kind="practice",
                                         context_mode="full_context", focus_problem=None) == base)
    ok &= _check("focus text prepends directive", "The student was assigned" in focused)
    ok &= _check("focus text names the sub-problem", "Practice Problem 2:" in focused)
    ok &= _check("focus text still contains full file", "Exercise:\n" in focused and base.split("Exercise:\n", 1)[1] in focused)
    ok &= _check("unresolvable focus -> unchanged text",
                 b.build_assignment_text(COURSE, "1", exercise_kind="practice",
                                         context_mode="full_context", focus_problem=999) == base)

    k_none = b.cache_key("tutor_07", COURSE, "1", exercise_kind="practice")
    k2 = b.cache_key("tutor_07", COURSE, "1", exercise_kind="practice", focus_problem=2)
    k3 = b.cache_key("tutor_07", COURSE, "1", exercise_kind="practice", focus_problem=3)
    ok &= _check("cache key differs by focus", k2 != k3 and k2 != k_none, (k_none, k2, k3))

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
