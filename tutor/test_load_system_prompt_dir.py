"""Checks that load_system_prompt honors an explicit prompts_dir.

Run:
    python -m tutor.test_load_system_prompt_dir
"""
from __future__ import annotations

from pathlib import Path

from tutor.run_tutor import PROMPTS_DIR, load_system_prompt


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True

    # Default folder (prompts_dir=None) still works and honors assignment override.
    default_text = load_system_prompt("tutor_07", assignment_override="ZZZMARKER")
    ok &= _check("default dir loads tutor_07", bool(default_text))
    ok &= _check("assignment override applied", "ZZZMARKER" in default_text)

    # Explicit prompts_dir pointing at the same folder yields the same content.
    explicit_text = load_system_prompt(
        "tutor_07", assignment_override="ZZZMARKER", prompts_dir=PROMPTS_DIR
    )
    ok &= _check("explicit dir matches default", explicit_text == default_text)

    # A prompts_dir that lacks the file raises FileNotFoundError.
    missing = False
    try:
        load_system_prompt("tutor_07", prompts_dir=Path(__file__).resolve().parent)
    except FileNotFoundError:
        missing = True
    ok &= _check("missing file in explicit dir raises", missing)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
