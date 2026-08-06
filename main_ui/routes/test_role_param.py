"""Flask test-client checks for the role param in main_ui.

Run:
    python -m main_ui.routes.test_role_param
"""
from __future__ import annotations

from main_ui.run_app import app
from main_ui.routes._validation import (
    DEFAULT_ROLE,
    role_default_prompt,
    validate_role,
)


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()

    ok &= _check("DEFAULT_ROLE is tutor", DEFAULT_ROLE == "tutor", DEFAULT_ROLE)
    ok &= _check("validate_role(tutor) ok", validate_role("tutor") is None)
    ok &= _check("validate_role(ta) fails", validate_role("ta") is not None)
    ok &= _check("validate_role(bogus) fails", validate_role("bogus") is not None)
    ok &= _check("role_default_prompt(tutor) == tutor_07",
                 role_default_prompt("tutor") == "tutor_07")

    # /embed default role renders and carries role=tutor in the page config.
    r = client.get("/embed?course=supply_chain_design&exercise=1")
    ok &= _check("/embed default role 200", r.status_code == 200, r.status_code)
    ok &= _check("/embed config has role tutor",
                 b'"role": "tutor"' in r.data or b'"role":"tutor"' in r.data)

    # explicit role=tutor renders; role=ta and role=bogus 404.
    ok &= _check("role=tutor 200",
                 client.get("/embed?course=supply_chain_design&exercise=1&role=tutor").status_code == 200)
    ok &= _check("role=ta 404",
                 client.get("/embed?course=supply_chain_design&exercise=1&role=ta").status_code == 404)
    ok &= _check("role=bogus 404",
                 client.get("/embed?course=supply_chain_design&exercise=1&role=bogus").status_code == 404)

    # bare host renders with role=tutor even though course is empty.
    root = client.get("/")
    ok &= _check("/ has role tutor",
                 b'"role": "tutor"' in root.data or b'"role":"tutor"' in root.data)

    # chat send with bad role 404s.
    bad = client.post("/api/chat", json={"text": "hi", "course": "supply_chain_design",
                                         "exercise": "1", "role": "bogus"})
    ok &= _check("chat role=bogus 404", bad.status_code == 404, bad.status_code)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
