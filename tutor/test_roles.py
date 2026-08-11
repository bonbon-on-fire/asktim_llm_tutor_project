"""Unit checks for the role registry.

Run:
    python -m tutor.test_roles
"""
from __future__ import annotations

from pathlib import Path

from tutor.roles import (
    DEFAULT_ROLE,
    ROLES,
    get_role,
    prompts_dir_for_prompt,
)


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    ok &= _check("default role is tutor", DEFAULT_ROLE == "tutor", DEFAULT_ROLE)

    tutor = get_role("tutor")
    ok &= _check("tutor role registered", tutor is not None)
    ok &= _check("tutor default prompt is tutor_09",
                 tutor is not None and tutor.default_prompt == "tutor_09")
    ok &= _check("tutor prompts_dir exists",
                 tutor is not None and tutor.prompts_dir.is_dir(), tutor.prompts_dir)

    ok &= _check("unknown role -> None", get_role("ta") is None)
    ok &= _check("None role -> None", get_role(None) is None)
    ok &= _check("ta not registered (scaffold only)", "ta" not in ROLES)

    d = prompts_dir_for_prompt("tutor_07")
    ok &= _check("reverse lookup finds tutor folder",
                 d is not None and (d / "tutor_07.txt").is_file(), d)
    ok &= _check("reverse lookup unknown prompt -> None",
                 prompts_dir_for_prompt("does_not_exist") is None)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
