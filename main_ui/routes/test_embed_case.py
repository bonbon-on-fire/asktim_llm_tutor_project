"""Flask test-client checks for case URL handling in main_ui /embed.

Run:
    python -m main_ui.routes.test_embed_case
"""
from __future__ import annotations

from main_ui.run_app import app
from utils.curriculum import discover_cases

# supply_chain_design ships the Chef Yourself case (case_1); curriculum is
# shared, so it's a valid active course in main_ui too.
CASE_COURSE = "supply_chain_design"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()

    cases = discover_cases(CASE_COURSE)
    both = client.get(f"/embed?course={CASE_COURSE}&exercise=1&case=1")
    ok &= _check("exercise+case -> 404", both.status_code == 404, both.status_code)

    if cases:
        n = cases[0]
        r = client.get(f"/embed?course={CASE_COURSE}&case={n}")
        ok &= _check("valid case renders", r.status_code == 200, r.status_code)
        ok &= _check("kind in page config", b'"exercise_kind": "case"' in r.data or b'"exercise_kind":"case"' in r.data)
    else:
        print(f"SKIP - {CASE_COURSE} has no case files")

    bad = client.get(f"/embed?course={CASE_COURSE}&case=9999")
    ok &= _check("invalid case -> 404", bad.status_code == 404, bad.status_code)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
