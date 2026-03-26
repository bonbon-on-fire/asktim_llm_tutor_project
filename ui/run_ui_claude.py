"""Batch runner that scores transcripts with the Claude judge."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from judge.run_judge_claude import JudgeError, judge_transcript
from students.run_student import list_personas

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"
_PROMPTS_DIR = _REPO_ROOT / "judge" / "prompts"
_RUBRICS_DIR = _REPO_ROOT / "judge" / "rubrics"

_RAW_SUBDIR_BY_TYPE = {"chaotic": "chaotic_raw", "chitchat": "chitchat_raw", "clueless": "clueless_raw"}
_TARGET_SUBDIR_BY_TYPE = {
    "chaotic": "chaotic_claude",
    "chitchat": "chitchat_claude",
    "clueless": "clueless_claude",
}

# ---------------------------------------------------------------------------
# Batch config (edit directly)
# ---------------------------------------------------------------------------

JUDGE_PROMPTS: list[str] = ["judge_05"]
JUDGE_RUBRICS: list[str] = ["rubric_05"]
STUDENT_PERSONAS: list[str] = [
    "clueless_01",
    "clueless_02",
    "clueless_03",
    "clueless_04",
    "clueless_05",
    "clueless_06"
]

# Optional transcript filtering per persona type.
# Empty list means "all transcript_*.json in raw folder".
RAW_TRANSCRIPTS: dict[str, list[str]] = {"chaotic": [], "chitchat": [], "clueless": []}


def _require_anthropic_api_key() -> None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return
    raise RuntimeError("ANTHROPIC_API_KEY environment variable is required but not set.")


def _discover_stems(directory: Path, suffix: str) -> set[str]:
    if not directory.exists():
        return set()
    return {p.stem for p in directory.glob(f"*{suffix}")}


def _parse_persona_name(persona: str) -> tuple[str, str]:
    match = re.match(r"^([a-zA-Z0-9]+)_(\d{2})$", persona)
    if not match:
        raise ValueError(f"Persona '{persona}' must match '<type>_<NN>' format (example: chaotic_01).")
    return match.group(1), match.group(2)


def _normalize_stem(name: str) -> str:
    stem = (name or "").strip()
    if stem.endswith(".json"):
        stem = stem[:-5]
    if not stem:
        raise ValueError("Transcript stem cannot be empty.")
    if "/" in stem or "\\" in stem:
        raise ValueError(f"Transcript '{name}' must be a stem only (no path separators).")
    return stem


def _raw_dir(persona_type: str) -> Path:
    return _TRANSCRIPTS_DIR / persona_type / _RAW_SUBDIR_BY_TYPE[persona_type]


def _target_dir(persona_type: str) -> Path:
    return _TRANSCRIPTS_DIR / persona_type / _TARGET_SUBDIR_BY_TYPE[persona_type]


def _discover_raw_stems(persona_type: str) -> list[str]:
    directory = _raw_dir(persona_type)
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob("transcript_*.json"))


def _selected_raw_stems(persona_type: str) -> list[str]:
    configured = RAW_TRANSCRIPTS.get(persona_type, [])
    if configured:
        return sorted({_normalize_stem(item) for item in configured})
    return _discover_raw_stems(persona_type)


def _validate_config() -> None:
    _require_anthropic_api_key()
    if not JUDGE_PROMPTS:
        raise ValueError("JUDGE_PROMPTS must contain at least one prompt.")
    if not JUDGE_RUBRICS:
        raise ValueError("JUDGE_RUBRICS must contain at least one rubric.")
    if not STUDENT_PERSONAS:
        raise ValueError("STUDENT_PERSONAS must contain at least one persona.")

    available_prompts = _discover_stems(_PROMPTS_DIR, ".txt")
    available_rubrics = _discover_stems(_RUBRICS_DIR, ".md")
    available_personas = set(list_personas())

    for prompt in JUDGE_PROMPTS:
        if prompt not in available_prompts:
            raise ValueError(f"Unknown judge prompt: {prompt}")
    for rubric in JUDGE_RUBRICS:
        if rubric not in available_rubrics:
            raise ValueError(f"Unknown judge rubric: {rubric}")

    seen_types: set[str] = set()
    for persona in STUDENT_PERSONAS:
        if persona not in available_personas:
            raise ValueError(f"Unknown student persona: {persona}")
        persona_type, _ = _parse_persona_name(persona)
        if persona_type not in _RAW_SUBDIR_BY_TYPE:
            raise ValueError(f"Unsupported persona type: {persona_type}")
        seen_types.add(persona_type)

    for persona_type in seen_types:
        raw_path = _raw_dir(persona_type)
        configured = RAW_TRANSCRIPTS.get(persona_type, [])
        if configured:
            for name in configured:
                stem = _normalize_stem(name)
                path = raw_path / f"{stem}.json"
                if not path.exists():
                    raise ValueError(f"Raw transcript not found: {path}")
        elif not _discover_raw_stems(persona_type):
            raise ValueError(f"No raw transcripts found for persona type '{persona_type}' in {raw_path}")


def _iter_persona_types() -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for persona in STUDENT_PERSONAS:
        persona_type, _ = _parse_persona_name(persona)
        if persona_type not in seen:
            seen.add(persona_type)
            ordered.append(persona_type)
    return ordered


def _copy_raw_to_target(*, persona_type: str, stem: str) -> Path:
    source = _raw_dir(persona_type) / f"{stem}.json"
    target_dir = _target_dir(persona_type)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{stem}.json"
    shutil.copyfile(source, target)

    # Re-judge safety: remove stale grade from copied baseline.
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return target
    if isinstance(payload, dict) and "grade" in payload:
        payload.pop("grade", None)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def main() -> int:
    try:
        _validate_config()
    except (RuntimeError, ValueError) as error:
        print(str(error))
        return 1

    failures: list[str] = []
    total_runs = 0

    try:
        for persona_type in _iter_persona_types():
            for source_stem in _selected_raw_stems(persona_type):
                baseline_path = _copy_raw_to_target(persona_type=persona_type, stem=source_stem)
                relative = str(baseline_path.relative_to(_TRANSCRIPTS_DIR)).replace("\\", "/")
                if relative.endswith(".json"):
                    relative = relative[:-5]

                for prompt_name in JUDGE_PROMPTS:
                    for rubric_name in JUDGE_RUBRICS:
                        total_runs += 1
                        try:
                            result = judge_transcript(
                                relative,
                                prompt_name=prompt_name,
                                rubric_name=rubric_name,
                                output_name=source_stem,
                            )
                            print(
                                "[Claude Judge] "
                                f"persona_type={persona_type} "
                                f"source={source_stem}.json "
                                f"prompt={prompt_name} "
                                f"rubric={rubric_name} "
                                f"score={result.total_score}/{result.max_score} "
                                f"saved={result.output_path.relative_to(_REPO_ROOT)}"
                            )
                        except JudgeError as error:
                            msg = (
                                f"persona_type={persona_type} "
                                f"source={source_stem}.json "
                                f"prompt={prompt_name} rubric={rubric_name} "
                                f"error={error}"
                            )
                            failures.append(msg)
                            print(f"[Claude Judge][FAILED] {msg}")
    except KeyboardInterrupt:
        print("\nClaude judging interrupted.")
        return 130

    if failures:
        print(f"\nClaude judging completed with failures: {len(failures)}/{total_runs}")
        for item in failures:
            print(f"- {item}")
        return 1

    print(f"\nClaude judging completed successfully: {total_runs} run(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
