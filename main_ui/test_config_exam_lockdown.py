"""Unit: MAIN_UI_EXAM_LOCKDOWN parsing into per-course lockdown config.

The env var accepts:
  * unset / a falsy word ("0","false","no","off","") -> nothing locked
  * a bare truthy word ("1","true","yes","on")        -> ALL courses (back-compat)
  * a comma-separated list of course slugs            -> only those courses

Run:
    python -m main_ui.test_config_exam_lockdown
"""
from __future__ import annotations

import os

from main_ui.config import load_config


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def _load(raw):
    """Load config with MAIN_UI_EXAM_LOCKDOWN set to *raw* (or unset when None)."""
    if raw is None:
        os.environ.pop("MAIN_UI_EXAM_LOCKDOWN", None)
    else:
        os.environ["MAIN_UI_EXAM_LOCKDOWN"] = raw
    return load_config()


def main() -> int:
    ok = True

    # --- Nothing locked: unset and falsy words. ---
    for raw in (None, "", "0", "false", "no", "off"):
        c = _load(raw)
        ok &= _check(
            f"raw={raw!r}: nothing locked",
            not c.exam_lockdown_all
            and c.exam_lockdown_courses == frozenset()
            and not c.is_exam_locked("supply_chain_design")
            and not c.is_exam_locked(None),
            (c.exam_lockdown_all, c.exam_lockdown_courses),
        )

    # --- Bare truthy word: ALL courses (backward compat with the old boolean). ---
    for raw in ("1", "true", "yes", "on", "TRUE"):
        c = _load(raw)
        ok &= _check(
            f"raw={raw!r}: all courses locked",
            c.exam_lockdown_all
            and c.is_exam_locked("supply_chain_design")
            and c.is_exam_locked("anything_else")
            and c.is_exam_locked(None),
            (c.exam_lockdown_all, c.exam_lockdown_courses),
        )

    # --- Single slug: only that course. ---
    c = _load("supply_chain_design")
    ok &= _check(
        "single slug: only that course locked",
        not c.exam_lockdown_all
        and c.exam_lockdown_courses == frozenset({"supply_chain_design"})
        and c.is_exam_locked("supply_chain_design")
        and not c.is_exam_locked("urban_transportation")
        and not c.is_exam_locked(None),
        (c.exam_lockdown_all, c.exam_lockdown_courses),
    )

    # --- Comma list with whitespace: trimmed, multiple courses. ---
    c = _load(" supply_chain_design , urban_transportation ")
    ok &= _check(
        "comma list: trimmed and both locked",
        c.exam_lockdown_courses == frozenset({"supply_chain_design", "urban_transportation"})
        and c.is_exam_locked("supply_chain_design")
        and c.is_exam_locked("urban_transportation")
        and not c.is_exam_locked("ai_edge"),
        (c.exam_lockdown_all, c.exam_lockdown_courses),
    )

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
