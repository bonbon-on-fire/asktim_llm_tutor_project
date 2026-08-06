"""Flask test-client checks for the problem-focus param in sandbox_ui.

Run:
    python -m sandbox_ui.routes.test_problem_focus
"""
from __future__ import annotations

from sandbox_ui.routes._validation import validate_problem
from sandbox_ui.run_app import app
from utils.curriculum import list_subproblems

COURSE = "supply_chain_design"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()

    subs = list_subproblems(COURSE, "1", "practice")
    if not subs:
        print("SKIP - no sub-problems for", COURSE, "practice 1")
        return 0
    n = subs[-1][0]

    r = client.get(f"/embed?course={COURSE}&practice=1&problem={n}")
    ok &= _check("valid problem renders", r.status_code == 200, r.status_code)
    ok &= _check("problem echoed in config",
                 (f'"problem": {n}'.encode() in r.data) or (f'"problem": "{n}"'.encode() in r.data))

    ok &= _check("out-of-range problem -> 404",
                 client.get(f"/embed?course={COURSE}&practice=1&problem=999").status_code == 404)
    ok &= _check("non-integer problem -> 404",
                 client.get(f"/embed?course={COURSE}&practice=1&problem=abc").status_code == 404)
    ok &= _check("no problem still renders",
                 client.get(f"/embed?course={COURSE}&practice=1").status_code == 200)

    bad = client.post("/api/chat", json={
        "text": "hi", "course": COURSE, "exercise": "1",
        "exercise_kind": "practice", "problem": "999",
    })
    ok &= _check("chat bad problem -> 404", bad.status_code == 404, bad.status_code)

    ok &= _check("validate_problem accepts int (JSON payload shape)",
                 validate_problem(COURSE, "1", "practice", n) is None, n)
    ok &= _check("validate_problem accepts digit string",
                 validate_problem(COURSE, "1", "practice", str(n)) is None, str(n))
    ok &= _check("validate_problem rejects non-digit",
                 validate_problem(COURSE, "1", "practice", "abc") is not None)
    ok &= _check("validate_problem out-of-range -> failure",
                 validate_problem(COURSE, "1", "practice", 999) is not None)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
