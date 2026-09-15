"""Standalone tests for utils.lectures (no pytest dependency).

Run with:
    python -m utils.test_lectures
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from utils.lectures import load_lecture_transcripts, load_recitation_transcripts

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    """Record and print a pass/fail result for the named assertion."""
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def test_missing_folder_returns_empty() -> None:
    """Assert a missing lectures/ folder yields an empty string."""
    with tempfile.TemporaryDirectory() as tmp:
        out = load_lecture_transcripts("demo", curriculum_root=Path(tmp))
        _check("missing lectures/ -> ''", out == "", f"got {out!r}")


def test_reads_and_orders_transcripts() -> None:
    """Assert transcripts are read in name order, labeled, and non-txt/empty files skipped."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        lect = root / "demo" / "lectures"
        lect.mkdir(parents=True)
        (lect / "lecture_02.txt").write_text("Second lecture body.", encoding="utf-8")
        (lect / "lecture_01.txt").write_text("First lecture body.", encoding="utf-8")
        (lect / "notes.md").write_text("ignored non-txt", encoding="utf-8")
        (lect / "empty.txt").write_text("   ", encoding="utf-8")

        out = load_lecture_transcripts("demo", curriculum_root=root)
        expected = (
            "[lecture_01]\nFirst lecture body.\n\n"
            "[lecture_02]\nSecond lecture body."
        )
        _check("orders by name, labels, skips non-txt/empty", out == expected, f"got {out!r}")


def test_missing_recitations_folder_returns_empty() -> None:
    """Assert a missing recitations/ folder yields an empty string."""
    with tempfile.TemporaryDirectory() as tmp:
        out = load_recitation_transcripts("demo", curriculum_root=Path(tmp))
        _check("missing recitations/ -> ''", out == "", f"got {out!r}")


def test_reads_and_orders_recitations() -> None:
    """Assert recitations are read in natural-number order, labeled, non-txt/empty skipped."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rec = root / "demo" / "recitations"
        rec.mkdir(parents=True)
        (rec / "recitation_10_1_review.txt").write_text("Tenth recitation.", encoding="utf-8")
        (rec / "recitation_2_1_lp.txt").write_text("Second recitation.", encoding="utf-8")
        (rec / "notes.md").write_text("ignored non-txt", encoding="utf-8")
        (rec / "empty.txt").write_text("   ", encoding="utf-8")

        out = load_recitation_transcripts("demo", curriculum_root=root)
        expected = (
            "[recitation_2_1_lp]\nSecond recitation.\n\n"
            "[recitation_10_1_review]\nTenth recitation."
        )
        _check("natural order, labels, skips non-txt/empty", out == expected, f"got {out!r}")


def main() -> int:
    """Run all tests and return 1 if any failed, else 0."""
    for t in (
        test_missing_folder_returns_empty,
        test_reads_and_orders_transcripts,
        test_missing_recitations_folder_returns_empty,
        test_reads_and_orders_recitations,
    ):
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
