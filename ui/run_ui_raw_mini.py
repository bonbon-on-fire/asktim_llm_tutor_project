"""
Interactive mini runner: continue a *_raw transcript from a chosen turn with a new tutor prompt.

Writes to ``transcripts/<type>/<type>_mini/``. Student stays on OpenAI (same as ``run_student``);
you choose the tutor provider (gpt/claude) for continuation.

Non-interactive / scripting: use ``python -m tutor.run_tutor_mini --help``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tutor.run_tutor_mini import (  # noqa: E402
    MiniContinuationParams,
    _RAW_SUBDIR_BY_PERSONA_TYPE,
    _discover_tutor_prompts,
    _require_openai_for_student,
    _require_tutor_key,
    list_raw_transcript_stems,
    load_raw_transcript,
    raw_transcript_dir,
    run_mini,
)
from ui.cli_utils import confirm_proceed, prompt_integer, prompt_single_selection  # noqa: E402


def _max_turn_in_transcript(data: dict) -> int:
    exchanges = data.get("exchanges")
    if not isinstance(exchanges, list):
        return 0
    best = 0
    for ex in exchanges:
        if isinstance(ex, dict):
            t = ex.get("turn")
            if isinstance(t, int) and t > best:
                best = t
    return best


def interactive_main() -> int:
    print("=== Raw transcript mini continuation ===")
    print("(Student model: OpenAI. Pick tutor provider for new turns.)\n")

    try:
        _require_openai_for_student()
    except RuntimeError as e:
        print(str(e))
        return 1

    persona_type = prompt_single_selection(
        "Persona type (transcripts folder)",
        sorted(_RAW_SUBDIR_BY_PERSONA_TYPE.keys()),
        required=True,
    )
    if not persona_type:
        return 1

    stems = list_raw_transcript_stems(persona_type)
    if not stems:
        print(f"No raw transcripts in {raw_transcript_dir(persona_type)}")
        return 1

    print("\nAvailable raw transcripts:")
    for i, stem in enumerate(stems, 1):
        print(f"  {i}) {stem}")
    while True:
        choice = input("Transcript (number): ").strip()
        try:
            n = int(choice)
        except ValueError:
            print(f"  Enter a number from 1 to {len(stems)}")
            continue
        if n < 1 or n > len(stems):
            print(f"  Enter a number from 1 to {len(stems)}")
            continue
        source_stem = stems[n - 1]
        break

    try:
        data = load_raw_transcript(persona_type, source_stem)
    except (OSError, json.JSONDecodeError) as e:
        print(f"Failed to load transcript: {e}")
        return 1

    max_turn = _max_turn_in_transcript(data)
    if max_turn < 1:
        print("Transcript has no valid exchanges with turn numbers.")
        return 1

    sp = data.get("student_persona", "?")
    print(f"\nLoaded {source_stem}.json  student_persona={sp}  last_turn={max_turn}")

    resume_after = prompt_integer(
        f"Resume after turn (inclusive history: keep turns 1 through this turn; max {max_turn})",
        min_value=1,
        max_value=max_turn,
    )
    if resume_after is None:
        print("Cancelled.")
        return 1

    additional = prompt_integer(
        "Additional turns (new student+tutor exchanges to generate)",
        min_value=1,
        max_value=100,
    )
    if additional is None:
        print("Cancelled.")
        return 1

    total_final = resume_after + additional
    tutor_provider = prompt_single_selection(
        "Tutor provider (for continuation only)",
        ["gpt", "claude"],
        required=True,
    )
    if not tutor_provider:
        return 1

    try:
        _require_tutor_key(tutor_provider)
    except RuntimeError as e:
        print(str(e))
        return 1

    prompts = _discover_tutor_prompts()
    if not prompts:
        print("No tutor prompts found in tutor/prompts/")
        return 1

    tutor_prompt = prompt_single_selection("Tutor prompt", prompts, required=True)
    if not tutor_prompt:
        return 1

    summary = (
        f"Continue {persona_type}/{source_stem}.json\n"
        f"  • History: turns 1–{resume_after} unchanged\n"
        f"  • Generate: {additional} new exchange(s) → final turn count up to {total_final}\n"
        f"  • Tutor: {tutor_prompt} ({tutor_provider.upper()})\n"
        f"  • Output: transcripts/{persona_type}/{persona_type}_mini/"
    )
    if not confirm_proceed(summary):
        print("Cancelled.")
        return 0

    params = MiniContinuationParams(
        persona_type=persona_type,
        source_transcript_stem=source_stem,
        resume_after_turn=resume_after,
        additional_turns=additional,
        tutor_prompt=tutor_prompt,
        tutor_provider=tutor_provider,
    )

    try:
        out = run_mini(params)
        print(f"\n[Mini] Saved {out.relative_to(_REPO_ROOT)}")
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(str(e))
        return 1
    return 0


def main() -> int:
    if len(sys.argv) > 1:
        from tutor.run_tutor_mini import main as tutor_cli_main

        return tutor_cli_main(sys.argv[1:])
    return interactive_main()


if __name__ == "__main__":
    raise SystemExit(main())
