"""Flask test-client checks for the problem-focus param in main_ui.

Run:
    python -m main_ui.routes.test_problem_focus
"""
from __future__ import annotations

from main_ui.run_app import app
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
    n = subs[-1][0]  # a valid, in-range problem number

    r = client.get(f"/embed?course={COURSE}&practice=1&problem={n}")
    ok &= _check("valid problem renders", r.status_code == 200, r.status_code)
    ok &= _check("problem echoed in config",
                 (f'"problem": {n}' .encode() in r.data) or (f'"problem": "{n}"'.encode() in r.data),
                 r.data[:0])

    ok &= _check("out-of-range problem -> 404",
                 client.get(f"/embed?course={COURSE}&practice=1&problem=999").status_code == 404)
    ok &= _check("non-integer problem -> 404",
                 client.get(f"/embed?course={COURSE}&practice=1&problem=abc").status_code == 404)

    # No problem -> unchanged (200, no focus).
    ok &= _check("no problem still renders",
                 client.get(f"/embed?course={COURSE}&practice=1").status_code == 200)

    # POST /api/chat: a bad problem 404s before streaming.
    bad = client.post("/api/chat", json={
        "text": "hi", "course": COURSE, "exercise": "1",
        "exercise_kind": "practice", "problem": "999",
    })
    ok &= _check("chat bad problem -> 404", bad.status_code == 404, bad.status_code)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
