"""
Batch mini-continuation runner for the reference transcript table in meeting_notes/04_28_2026.md.

For each entry in the reference table, resumes from the flagged turn using tutor_05 (Claude).
Transcripts with two flagged turns produce two mini files: transcript_XXXX_01.json and
transcript_XXXX_02.json. Single-turn transcripts produce transcript_XXXX_01.json.

Usage:
    python ui/run_ui_raw_mini_batch_reference.py [--dry-run]

Options:
    --dry-run   Print the planned runs without executing them.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_REPO_ROOT / ".env")

from tutor.run_tutor_mini import (  # noqa: E402
    MiniContinuationParams,
    _require_openai_for_student,
    _require_tutor_key,
    raw_transcript_dir,
    run_mini,
)

TUTOR_PROMPT = "tutor_05"
TUTOR_PROVIDER = "claude"
ADDITIONAL_TURNS = 3

# Reference table from meeting_notes/04_28_2026.md.
# Each entry: (persona_type, source_stem, resume_from_turn, output_suffix)
# Output filename: transcript_XXXX_{output_suffix}.json
REFERENCE_RUNS: list[tuple[str, str, int, str]] = [
    ("chaotic", "transcript_0007",  3,  "01"),
    ("chaotic", "transcript_0015",  8,  "01"),
    ("chaotic", "transcript_0015",  9,  "02"),
    ("chaotic", "transcript_0026",  4,  "01"),
    ("chaotic", "transcript_0028",  8,  "01"),
    ("chaotic", "transcript_0079",  6,  "01"),
    ("chaotic", "transcript_0090",  4,  "01"),
    ("chaotic", "transcript_0090",  8,  "02"),
    ("chaotic", "transcript_0097",  5,  "01"),
    ("chaotic", "transcript_0107",  2,  "01"),
    ("chaotic", "transcript_0115",  4,  "01"),
    ("chaotic", "transcript_0124",  6,  "01"),
    ("chaotic", "transcript_0124",  8,  "02"),
    ("chaotic", "transcript_0142",  1,  "01"),
    ("chaotic", "transcript_0142",  8,  "02"),
    ("clueless", "transcript_0013", 1,  "01"),
    ("clueless", "transcript_0018", 4,  "01"),
    ("clueless", "transcript_0018", 10, "02"),
    ("clueless", "transcript_0025", 9,  "01"),
    ("clueless", "transcript_0123", 8,  "01"),
    ("clueless", "transcript_0123", 9,  "02"),
    ("clueless", "transcript_0218", 7,  "01"),
    ("clueless", "transcript_0242", 2,  "01"),
    ("clueless", "transcript_0248", 3,  "01"),
    ("clueless", "transcript_0297", 8,  "01"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Print planned runs without executing.")
    args = parser.parse_args(argv)

    if not args.dry_run:
        try:
            _require_openai_for_student()
            _require_tutor_key(TUTOR_PROVIDER)
        except RuntimeError as e:
            print(str(e))
            return 1

    total = len(REFERENCE_RUNS)
    print(f"Reference batch: {total} runs | prompt={TUTOR_PROMPT} provider={TUTOR_PROVIDER} additional_turns={ADDITIONAL_TURNS}\n")

    failures: list[str] = []

    for i, (persona_type, source_stem, resume_from, suffix) in enumerate(REFERENCE_RUNS, 1):
        output_stem = f"{source_stem}_{suffix}"
        raw_path = raw_transcript_dir(persona_type) / f"{source_stem}.json"
        label = f"[{i:02d}/{total}] {persona_type}/{source_stem} turn={resume_from} -> {output_stem}"

        if not raw_path.exists():
            msg = f"  SKIP — raw file not found: {raw_path}"
            print(f"{label}\n{msg}\n")
            failures.append(f"{label}: raw not found")
            continue

        if args.dry_run:
            print(f"{label}  (dry-run)\n")
            continue

        print(label)
        try:
            params = MiniContinuationParams(
                persona_type=persona_type,
                source_transcript_stem=source_stem,
                resume_from_turn=resume_from,
                additional_turns=ADDITIONAL_TURNS,
                tutor_prompt=TUTOR_PROMPT,
                tutor_provider=TUTOR_PROVIDER,
                output_stem=output_stem,
            )
            out_path = run_mini(params)
            print(f"  OK -> {out_path.relative_to(_REPO_ROOT)}\n")
        except Exception as e:  # noqa: BLE001
            msg = f"  FAIL - {e}"
            print(f"{msg}\n")
            failures.append(f"{label}: {e}")

    if failures:
        print(f"\n{len(failures)} failure(s):")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"Done. {total} run(s) completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
