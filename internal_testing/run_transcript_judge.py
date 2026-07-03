"""
Interactive runner that grades all raw transcripts using either GPT or Claude judge.

Reads from transcripts/{persona}/{persona}_raw/ and writes graded copies
to transcripts/{persona}/{persona}_gpt/ or transcripts/{persona}/{persona}_claude/.

Run with interactive CLI:
    python -m internal_ui.run_ui_judge

Or run with command-line arguments:
    python -m internal_ui.run_ui_judge --provider gpt --prompt judge_06 --rubric rubric_06
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
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

from students.run_student import list_personas
from internal_ui.cli_utils import (
    confirm_proceed,
    prompt_single_selection,
)

TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"

# ---------------------------------------------------------------------------
# Parallel workers — override at runtime with the JUDGE_WORKERS env var
# (e.g. JUDGE_WORKERS=24) or change this default to control concurrency.
# ---------------------------------------------------------------------------
PARALLEL_WORKERS = int(os.environ.get("JUDGE_WORKERS", "6"))


def _require_openai_api_key() -> None:
    """Raise RuntimeError if OPENAI_API_KEY is not set in the environment."""
    if os.environ.get("OPENAI_API_KEY"):
        return
    raise RuntimeError(
        "OPENAI_API_KEY environment variable is required but not set."
    )


def _require_anthropic_api_key() -> None:
    """Raise RuntimeError if ANTHROPIC_API_KEY is not set in the environment."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    raise RuntimeError(
        "ANTHROPIC_API_KEY environment variable is required but not set."
    )


def _discover_raw_transcripts(source_suffix: str = "raw") -> list[Path]:
    """Find transcript files under *_{source_suffix}/ for supported persona families."""
    active_types = {
        persona.split("_", 1)[0].strip().lower()
        for persona in list_personas()
        if "_" in persona
    }
    all_files = sorted(TRANSCRIPTS_DIR.glob(f"*/*_{source_suffix}/transcript_*.json"))
    return [
        path
        for path in all_files
        if path.parent.parent.name.strip().lower() in active_types
    ]


def _discover_judge_prompts() -> list[str]:
    """Return available judge prompt names from judge/prompts/."""
    judge_prompts_dir = _REPO_ROOT / "judge" / "prompts"
    if not judge_prompts_dir.exists():
        return []
    return sorted(path.stem for path in judge_prompts_dir.glob("judge_*.txt"))


def _discover_judge_rubrics() -> list[str]:
    """Return available judge rubric names from judge/rubrics/."""
    judge_rubrics_dir = _REPO_ROOT / "judge" / "rubrics"
    if not judge_rubrics_dir.exists():
        return []
    return sorted(path.stem for path in judge_rubrics_dir.glob("rubric_*.md"))


def _provider_target_path(
    raw_path: Path,
    provider: str,
    source_suffix: str = "raw",
    output_suffix: str | None = None,
) -> Path:
    """Map a source transcript path to its graded counterpart folder.

    If *output_suffix* is given, the target folder is ``*_{provider}_{output_suffix}/``.
    Otherwise falls back to the auto-derived name:
    ``*_raw/`` → ``*_{provider}/``, ``*_{suffix}/`` → ``*_{provider}_{suffix}/``.
    """
    persona_dir = raw_path.parent.parent
    persona_type = persona_dir.name
    if output_suffix is not None:
        target_folder = f"{persona_type}_{provider}_{output_suffix}"
    elif source_suffix == "raw":
        target_folder = f"{persona_type}_{provider}"
    else:
        target_folder = f"{persona_type}_{provider}_{source_suffix}"
    target_dir = persona_dir / target_folder
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / raw_path.name


def _relative_stem(path: Path) -> str:
    """Return the transcript name relative to TRANSCRIPTS_DIR without .json."""
    rel = path.relative_to(TRANSCRIPTS_DIR).as_posix()
    return rel[:-5] if rel.endswith(".json") else rel


def _grade_one(
    raw_path: Path,
    target_path: Path,
    *,
    provider: str,
    prompt_name: str,
    rubric_name: str,
) -> dict[str, Any]:
    """Copy a raw transcript to its target path, then grade it in place."""
    if target_path.exists():
        print(
            f"  [WARN] Overwriting existing file: "
            f"{target_path.relative_to(_REPO_ROOT)}"
        )
    shutil.copyfile(raw_path, target_path)

    from judge.run_judge import judge_transcript

    result = judge_transcript(
        _relative_stem(target_path),
        provider=provider,
        prompt_name=prompt_name,
        rubric_name=rubric_name,
        output_name=target_path.stem,
    )

    graded = json.loads(result.output_path.read_text(encoding="utf-8"))
    grade = graded.get("grade", {})
    section_scores: list[str] = []
    for sid, section in grade.get("sections", {}).items():
        base = section.get("base", {})
        section_scores.append(f"{sid}={base.get('score', '?')}/{base.get('max', '?')}")

    return {
        "raw_path": raw_path,
        "name": _relative_stem(target_path),
        "score": result.total_score,
        "max_score": result.max_score,
        "output_path": result.output_path,
        "section_scores": "  ".join(section_scores),
    }


_progress_lock = threading.Lock()
_progress_done = 0


def _print_result(info: dict[str, Any], total: int, provider: str) -> None:
    """Print a one-line progress and score summary for a completed grading task."""
    global _progress_done
    with _progress_lock:
        _progress_done += 1
        n = _progress_done
    
    provider_label = provider.upper()
    print(
        f"[{provider_label} Judge] [{n}/{total}] "
        f"score={info['score']}/{info['max_score']}  "
        f"source={info['raw_path'].relative_to(_REPO_ROOT)}  "
        f"saved={info['output_path'].relative_to(_REPO_ROOT)}"
    )
    indent = " " * (len(provider_label) + 9)  # Match the bracket length
    print(f"{indent}{info['section_scores']}")


def _get_interactive_config() -> tuple[str, str, str]:
    """Get judge configuration through interactive CLI prompts."""
    print("=== Transcript Judging Configuration ===")
    
    # Provider selection
    provider = prompt_single_selection(
        "Judge provider",
        ["gpt", "claude"],
        required=True,
    )
    
    # Judge prompt selection
    available_prompts = _discover_judge_prompts()
    if not available_prompts:
        raise RuntimeError("No judge prompts found in judge/prompts/")
    
    prompt_name = prompt_single_selection(
        "Judge prompt",
        available_prompts,
        required=True,
    )
    
    # Judge rubric selection
    available_rubrics = _discover_judge_rubrics()
    if not available_rubrics:
        raise RuntimeError("No judge rubrics found in judge/rubrics/")
    
    rubric_name = prompt_single_selection(
        "Judge rubric",
        available_rubrics,
        required=True,
    )
    
    return provider, prompt_name, rubric_name


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Grade all raw transcripts with GPT or Claude judge into provider-specific folders",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (default)
  python -m internal_ui.run_ui_judge
  
  # Command-line mode
  python -m internal_ui.run_ui_judge --provider gpt --prompt judge_05 --rubric rubric_05
        """,
    )
    parser.add_argument(
        "--provider", choices=["gpt", "claude"],
        help="Judge provider to use: gpt or claude",
    )
    parser.add_argument(
        "--prompt",
        help="Judge prompt stem (from judge/prompts/judge_*.txt)",
    )
    parser.add_argument(
        "--rubric",
        help="Judge rubric stem (from judge/rubrics/rubric_*.md)",
    )
    parser.add_argument(
        "--source-suffix",
        default="raw",
        help="Subfolder suffix to read from: 'raw' (default) or 'mini'. "
             "Output folder is *_{provider}/ for 'raw', *_{provider}_{suffix}/ otherwise.",
    )
    parser.add_argument(
        "--output-suffix",
        default=None,
        help="Override output folder suffix. Target becomes *_{provider}_{suffix}/. "
             "If omitted, derived from --source-suffix.",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt (useful for non-interactive / background runs).",
    )

    return parser.parse_args()


def _run_judging(provider: str, prompt_name: str, rubric_name: str, source_suffix: str = "raw", yes: bool = False, output_suffix: str | None = None) -> int:
    """Run the judging process with the given configuration."""
    # Check API key based on provider
    try:
        if provider == "gpt":
            _require_openai_api_key()
        elif provider == "claude":
            _require_anthropic_api_key()
    except RuntimeError as error:
        print(f"API key error: {error}")
        return 1

    source_files = _discover_raw_transcripts(source_suffix)
    if not source_files:
        print(f"No *_{source_suffix}/ transcripts found under {TRANSCRIPTS_DIR}")
        return 1

    if output_suffix is not None:
        target_label = f"*_{provider}_{output_suffix}/"
    elif source_suffix == "raw":
        target_label = f"*_{provider}/"
    else:
        target_label = f"*_{provider}_{source_suffix}/"

    # Show summary and get confirmation
    summary = (
        f"Will grade {len(source_files)} *_{source_suffix}/ transcripts using:\n"
        f"  • Provider: {provider.upper()}\n"
        f"  • Judge prompt: {prompt_name}\n"
        f"  • Judge rubric: {rubric_name}\n"
        f"  • Output: {target_label}\n"
        f"  • Parallel workers: {PARALLEL_WORKERS}"
    )

    if not yes and not confirm_proceed(summary):
        print("Cancelled.")
        return 0

    workers = PARALLEL_WORKERS
    provider_label = provider.upper()
    print(
        f"[{provider_label} Judge] Grading {len(source_files)} transcripts  "
        f"prompt={prompt_name}  rubric={rubric_name}  parallel={workers}"
    )

    tasks: list[tuple[Path, Path]] = []
    for raw_path in source_files:
        target_path = _provider_target_path(raw_path, provider, source_suffix, output_suffix)
        tasks.append((raw_path, target_path))

    global _progress_done
    _progress_done = 0
    total = len(tasks)
    all_scores: list[dict[str, Any]] = []
    failed = 0

    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    _grade_one, source_path, target_path,
                    provider=provider,
                    prompt_name=prompt_name,
                    rubric_name=rubric_name,
                ): (source_path, target_path)
                for source_path, target_path in tasks
            }
            for future in as_completed(futures):
                source_path, _ = futures[future]
                try:
                    info = future.result()
                    all_scores.append(info)
                    _print_result(info, total, provider)
                except Exception as error:  # Catch both JudgeError and import errors
                    failed += 1
                    with _progress_lock:
                        _progress_done += 1
                        n = _progress_done
                    print(
                        f"[{provider_label} Judge] [{n}/{total}] FAILED "
                        f"source={source_path.relative_to(_REPO_ROOT)}: {error}"
                    )
    except KeyboardInterrupt:
        print(f"\n{provider_label} judging interrupted.")
        return 130

    scores_only = [s["score"] for s in all_scores]
    mean_score = sum(scores_only) / len(scores_only) if scores_only else 0.0
    print(
        f"\n[{provider_label} Judge] Done. "
        f"graded={len(all_scores)}  failed={failed}  "
        f"mean={mean_score:.1f}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point: get config via interactive prompts or args, then run judging."""
    args = _parse_args()
    
    # Determine if we should use interactive mode
    use_interactive = not all([args.provider, args.prompt, args.rubric])
    
    try:
        if use_interactive:
            provider, prompt_name, rubric_name = _get_interactive_config()
        else:
            provider = args.provider
            prompt_name = args.prompt
            rubric_name = args.rubric

            # Validate that all required args are provided
            if not provider:
                print("Error: --provider is required in non-interactive mode")
                return 1
            if not prompt_name:
                print("Error: --prompt is required in non-interactive mode")
                return 1
            if not rubric_name:
                print("Error: --rubric is required in non-interactive mode")
                return 1

        return _run_judging(provider, prompt_name, rubric_name, source_suffix=args.source_suffix, yes=args.yes, output_suffix=args.output_suffix)
        
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}")
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
