"""Standalone test: judge reconstructs per-turn figures from transcript exchanges.

Run with:
    python -m eval.tutor_judge.test_judge_figures
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from utils.figures import discover_figures, discover_figures_for_sources, figure_filenames

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


def _figures_for_transcript(course, exercise_number, exchanges, curriculum_root=None):
    """Union of exercise figures + every retrieved-item figure across exchanges.

    Mirrors the judge/payload reconstruction: exercise figures first, then the
    lecture/practice figures for items retrieved on any turn, deduped by name.
    """
    names = figure_filenames(discover_figures(course, exercise_number, curriculum_root))
    sources = []
    for ex in exchanges or []:
        for rec in ex.get("retrieved") or []:
            sources.append(rec.get("source", ""))
    names += figure_filenames(discover_figures_for_sources(course, sources, curriculum_root))
    return list(dict.fromkeys(names))


def test_union_exercise_and_retrieved_figures() -> None:
    """Assert transcript figure union = exercise figures + retrieved lecture figures."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        figdir = root / "demo" / "figures"
        figdir.mkdir(parents=True)
        (figdir / "exercise_5_ex.png").write_bytes(b"\x89PNG\r\n")
        (figdir / "lecture_5_two_cities.png").write_bytes(b"\x89PNG\r\n")
        (figdir / "lecture_6_other.png").write_bytes(b"\x89PNG\r\n")

        exchanges = [
            {"retrieved": [{"source": "local:lecture_5_intro"}, {"source": "local:key_concepts"}]},
            {"retrieved": [{"source": "local:lecture_5_intro"}]},  # dup across turns
        ]
        names = _figures_for_transcript("demo", "5", exchanges, curriculum_root=root)
        _check(
            "exercise first, then retrieved lecture, deduped; unretrieved lecture_6 absent",
            names == ["exercise_5_ex.png", "lecture_5_two_cities.png"],
            f"got {names}",
        )


def main() -> int:
    tests = [test_union_exercise_and_retrieved_figures]
    for t in tests:
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
