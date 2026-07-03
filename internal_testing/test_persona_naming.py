"""Standalone tests for version-optional persona naming (no pytest).

Run with:
    python -m internal_testing.test_persona_naming
"""

from __future__ import annotations

from internal_testing.cli_utils import parse_persona_type_and_version, group_personas_by_type
from internal_testing.run_transcript import RunConfig

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def _raises(fn) -> bool:
    try:
        fn()
        return False
    except ValueError:
        return True


def test_parser_accepts_bare_and_versioned() -> None:
    _check("bare -> (type, '')", parse_persona_type_and_version("clueless") == ("clueless", ""))
    _check("versioned -> (type, NN)", parse_persona_type_and_version("clueless_01") == ("clueless", "01"))
    _check("bad shape raises", _raises(lambda: parse_persona_type_and_version("clueless_1")))
    _check("empty raises", _raises(lambda: parse_persona_type_and_version("")))


def test_group_by_type_handles_bare() -> None:
    groups = group_personas_by_type(["clueless", "chaotic", "cooperative"])
    _check("bare names group by themselves", groups == {"clueless": ["clueless"], "chaotic": ["chaotic"], "cooperative": ["cooperative"]}, f"got {groups}")


def test_student_persona_property() -> None:
    bare = RunConfig(tutor_prompt="t", persona_type="clueless", persona_version="",
                     course="c", exercise_number="01", turn_size=10)
    _check("empty version -> bare", bare.student_persona == "clueless", f"got {bare.student_persona!r}")
    versioned = RunConfig(tutor_prompt="t", persona_type="clueless", persona_version="01",
                          course="c", exercise_number="01", turn_size=10)
    _check("version -> type_NN", versioned.student_persona == "clueless_01", f"got {versioned.student_persona!r}")


def main() -> int:
    for t in (test_parser_accepts_bare_and_versioned, test_group_by_type_handles_bare, test_student_persona_property):
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
