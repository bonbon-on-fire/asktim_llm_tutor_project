"""Parser checks for sub-problem headers in a week file.

Run:
    python -m utils.test_subproblems
"""
from __future__ import annotations

from utils.curriculum import list_subproblems, subproblem_label

COURSE = "supply_chain_design"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True

    # Practice file: "Practice Problem N:" headers.
    pp = list_subproblems(COURSE, "1", "practice")
    ok &= _check("practice headers found", len(pp) >= 2, len(pp))
    ok &= _check("practice first is (1, title)", pp and pp[0][0] == 1 and bool(pp[0][1]), pp[:1])

    # Graded file: "Graded Assignment N:" headers.
    ga = list_subproblems(COURSE, "1", "exercise")
    ok &= _check("graded headers found", len(ga) >= 2, len(ga))
    ok &= _check("graded first is (1, title)", ga and ga[0][0] == 1, ga[:1])

    # Kind isolation: practice parse and graded parse yield different, non-overlapping
    # header sets — a practice file must never surface "Graded Assignment" headers.
    ok &= _check("practice kind ignores graded headers",
                 pp != ga and {t for _, t in pp}.isdisjoint({t for _, t in ga}),
                 (pp[:1], ga[:1]))

    # subproblem_label
    lbl = subproblem_label(COURSE, "1", "practice", "2")
    ok &= _check("label for problem 2", lbl is not None and lbl.startswith("Practice Problem 2:"), lbl)
    ok &= _check("label accepts int problem", subproblem_label(COURSE, "1", "practice", 2) == lbl)
    ok &= _check("label None for missing n", subproblem_label(COURSE, "1", "practice", "999") is None)

    # Missing file -> [] and None (no crash).
    ok &= _check("missing file -> []", list_subproblems(COURSE, "99", "practice") == [])
    ok &= _check("missing file -> label None", subproblem_label(COURSE, "99", "practice", "1") is None)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
