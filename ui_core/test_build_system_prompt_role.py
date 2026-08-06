"""Checks that the bridge resolves the prompt folder via the role registry.

Run:
    python -m ui_core.test_build_system_prompt_role
"""
from __future__ import annotations

from ui_core.tutor_bridge import TutorBridge


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    bridge = TutorBridge()

    # tutor_07 is owned by the tutor role -> loads from tutor/prompts and the
    # assignment override is applied, proving the right file was read.
    prompt = bridge.build_system_prompt("tutor_07", "ZZZMARKER", course="")
    ok &= _check("build_system_prompt loads tutor_07", bool(prompt))
    ok &= _check("assignment override present", "ZZZMARKER" in prompt)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
