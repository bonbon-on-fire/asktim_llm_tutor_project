"""
Batch runner that grades transcript bundles using the GPT batch judge.

Reads batch files from transcripts/batches/batches_raw/batch_XX/ and writes
graded results to transcripts/batches/batches_gpt/batch_XX/.

Usage:
    python -m ui.run_ui_batch_gpt --batch-type 01
    python -m ui.run_ui_batch_gpt --batch-type 02 --prompt judge_06 --rubric rubric_06
"""

from __future__ import annotations

import argparse
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env")

from judge.run_judge_batch_gpt import JudgeError, JudgeResult, judge_transcript_batch

BATCHES_DIR = _REPO_ROOT / "transcripts" / "batches"

# ---------------------------------------------------------------------------
# Parallel workers — change this value to control concurrency.
# ---------------------------------------------------------------------------
PARALLEL_WORKERS = 6


def _require_openai_api_key() -> None:
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY"):
        return
    raise RuntimeError(
        "OPENAI_API_KEY (or OPENAI_KEY) environment variable is required but not set."
    )


def _discover_batch_files(batch_type: str) -> list[Path]:
    """Find all batch_*.txt files for the given batch type."""
    raw_dir = BATCHES_DIR / "batches_raw" / f"batch_{batch_type}"
    if not raw_dir.exists():
        return []
    return sorted(raw_dir.glob("batch_*.txt"))


def _output_path_for(batch_file: Path, batch_type: str) -> Path:
    """Map a raw batch file to its graded output path."""
    out_dir = BATCHES_DIR / "batches_gpt" / f"batch_{batch_type}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / batch_file.with_suffix(".json").name


def _grade_one_batch(
    batch_file: Path,
    output_path: Path,
    *,
    prompt_name: str,
    rubric_name: str,
) -> dict[str, Any]:
    """Grade a single batch file and return summary info."""
    if output_path.exists():
        print(
            f"  [WARN] Overwriting existing file: "
            f"{output_path.relative_to(_REPO_ROOT)}"
        )

    result = judge_transcript_batch(
        str(batch_file),
        prompt_name=prompt_name,
        rubric_name=rubric_name,
        output_path=str(output_path),
    )

    return {
        "batch_file": batch_file,
        "score": result.total_score,
        "max_score": result.max_score,
        "output_path": result.output_path,
    }


_progress_lock = threading.Lock()
_progress_done = 0


def _print_result(info: dict[str, Any], total: int) -> None:
    global _progress_done
    with _progress_lock:
        _progress_done += 1
        n = _progress_done
    print(
        f"[GPT Batch Judge] [{n}/{total}] "
        f"score={info['score']}/{info['max_score']}  "
        f"batch={info['batch_file'].name}  "
        f"saved={info['output_path'].relative_to(_REPO_ROOT)}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Grade all batch files of a given type with GPT batch judge."
    )
    parser.add_argument(
        "--batch-type", required=True,
        help="Batch type number: 01, 02, or 03.",
    )
    parser.add_argument(
        "--prompt", default="judge_05",
        help="Judge prompt stem (default: judge_05).",
    )
    parser.add_argument(
        "--rubric", default="rubric_05",
        help="Judge rubric stem (default: rubric_05).",
    )
    args = parser.parse_args(argv)

    try:
        _require_openai_api_key()
    except RuntimeError as error:
        print(str(error))
        return 1

    batch_type = args.batch_type.zfill(2)
    batch_files = _discover_batch_files(batch_type)
    if not batch_files:
        print(
            f"No batch files found under "
            f"{BATCHES_DIR / 'batches_raw' / f'batch_{batch_type}'}"
        )
        return 1

    workers = PARALLEL_WORKERS
    print(
        f"[GPT Batch Judge] Grading {len(batch_files)} batches (type {batch_type})  "
        f"prompt={args.prompt}  rubric={args.rubric}  parallel={workers}"
    )

    tasks: list[tuple[Path, Path]] = []
    for bf in batch_files:
        tasks.append((bf, _output_path_for(bf, batch_type)))

    global _progress_done
    _progress_done = 0
    total = len(tasks)
    all_scores: list[dict[str, Any]] = []
    failed = 0

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _grade_one_batch, bf, out,
                    prompt_name=args.prompt, rubric_name=args.rubric,
                ): (bf, out)
                for bf, out in tasks
            }
            for future in as_completed(futures):
                bf, _ = futures[future]
                try:
                    info = future.result()
                    all_scores.append(info)
                    _print_result(info, total)
                except JudgeError as error:
                    failed += 1
                    with _progress_lock:
                        _progress_done += 1
                        n = _progress_done
                    print(
                        f"[GPT Batch Judge] [{n}/{total}] FAILED "
                        f"batch={bf.name}: {error}"
                    )
    except KeyboardInterrupt:
        print("\nGPT batch judging interrupted.")
        return 130

    scores_only = [s["score"] for s in all_scores]
    mean_score = sum(scores_only) / len(scores_only) if scores_only else 0.0
    print(
        f"\n[GPT Batch Judge] Done. "
        f"graded={len(all_scores)}  failed={failed}  "
        f"mean={mean_score:.1f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
