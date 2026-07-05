"""
Interactive runner that generates raw (unjudged) tutor/student transcripts.

Run with interactive CLI:
    python -m internal_testing.run_transcript

Or run with command-line arguments:
    python -m internal_testing.run_transcript --provider claude --tutor tutor_03 --personas clueless --course philosophy --exercise 01 --turn-size 10 --trials 2
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage  # pyright: ignore[reportMissingImports]

from students.run_student import build_graph as build_student_graph
from students.run_student import get_next_student_message, list_personas
from tutor.run_tutor import (
    create_tutor_graph,
    get_tutor_reply,
    load_system_prompt,
    parse_tutor_response,
)
from internal_testing.cli_utils import (
    confirm_proceed,
    group_personas_by_type,
    parse_persona_type,
    prompt_integer,
    prompt_numbered_selection,
    prompt_single_selection,
)
from utils.curriculum import discover_exercises as _discover_course_exercises
from utils.curriculum import exercise_path
from utils.figures import discover_figures, figure_filenames
from utils.lectures import load_lecture_transcripts

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TUTOR_PROMPTS_DIR = _REPO_ROOT / "tutor" / "prompts"
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"

_TUTOR_GREETING = "Hi. What would you like to work on today?"
_RAW_SUBDIR_BY_PERSONA_TYPE: dict[str, str] = {
    "chaotic": "chaotic_raw",
    "cooperative": "cooperative_raw",
    "clueless": "clueless_raw",
}
_TUTOR_CALL_MAX_RETRIES = 2
PARALLEL_WORKERS = 6
_SAVE_LOCK = threading.Lock()

# ---------------------------------------------------------------------------
# Default bundle config (can be overridden by CLI)
# ---------------------------------------------------------------------------

DEFAULT_TUTOR_PROMPTS: list[str] = ["tutor_03"]
DEFAULT_STUDENT_PERSONAS: list[str] = ["clueless"]
DEFAULT_COURSE_EXERCISES: list[tuple[str, str]] = [("philosophy", "01")]
DEFAULT_TURN_SIZE: int = 10
DEFAULT_TRIALS: int = 2


@dataclass(frozen=True)
class RunConfig:
    """Single conversation run configuration for one tutor/persona/course/exercise tuple."""

    tutor_prompt: str
    persona_type: str
    course: str
    exercise_number: str
    turn_size: int
    provider: str = "gpt"

    @property
    def student_persona(self) -> str:
        """Persona identifier — the bare persona type."""
        return self.persona_type


@dataclass(frozen=True)
class BundleConfig:
    """Configuration for the entire bundle run."""
    provider: str
    tutor_prompts: list[str]
    student_personas: list[str]
    course_exercises: list[tuple[str, str]]
    turn_size: int
    trials: int
    output_suffix: str = "raw"


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


def _discover_stems(directory: Path, suffix: str) -> list[str]:
    """Return sorted file stems (without extension) for files matching the given suffix in directory."""
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob(f"*{suffix}"))


def _discover_tutor_prompts() -> list[str]:
    """Return available tutor prompt names from tutor/prompts/."""
    return _discover_stems(_TUTOR_PROMPTS_DIR, ".txt")


def _discover_courses() -> list[str]:
    """Return available course folder names from curriculum/."""
    if not _CURRICULUM_DIR.exists():
        return []
    return sorted(path.name for path in _CURRICULUM_DIR.iterdir() if path.is_dir())


def _discover_exercises(course: str) -> list[str]:
    """Return exercise numbers available for a course, non-padded (e.g. ['1', '2'])."""
    return _discover_course_exercises(course)


def _parse_persona_name(persona_name: str) -> str:
    """Validate a bare persona name and return its type; raises ValueError on bad format."""
    return parse_persona_type(persona_name)


def _build_assignment_text(course: str, exercise_number: str, turn_size: int) -> str:
    """Build the full assignment string: course context + syllabus (optional) + exercise text + run config."""
    course_dir = _CURRICULUM_DIR / course
    exercise_text = exercise_path(course, exercise_number).read_text(encoding="utf-8").strip()

    parts: list[str] = []

    course_path = course_dir / "course.txt"
    if course_path.exists():
        parts.append("Course context:\n" + course_path.read_text(encoding="utf-8").strip())

    syllabus_path = course_dir / "syllabus.txt"
    if syllabus_path.exists():
        parts.append("Syllabus:\n" + syllabus_path.read_text(encoding="utf-8").strip())

    lectures = load_lecture_transcripts(course)
    if lectures:
        parts.append("Lecture transcripts:\n" + lectures)

    parts.append("Exercise:\n" + exercise_text)
    parts.append(f"Run configuration:\n- Planned conversation length: {turn_size} student+tutor exchanges.")
    return "\n\n".join(parts)


def _next_transcript_number(output_dir: Path) -> str:
    """Return the next available zero-padded transcript number in output_dir (filling gaps)."""
    used_numbers: set[int] = set()
    if output_dir.exists():
        for path in output_dir.glob("transcript_*.json"):
            match = re.match(r"^transcript_(\d+)\.json$", path.name)
            if match:
                used_numbers.add(int(match.group(1)))
    next_num = 1
    while next_num in used_numbers:
        next_num += 1
    return f"{next_num:02d}"


def _validate_bundle_config(config: BundleConfig) -> None:
    """Validate the bundle config against available assets; raises ValueError/RuntimeError on bad config."""
    if config.provider == "claude":
        _require_anthropic_api_key()
    else:
        _require_openai_api_key()
    if config.turn_size <= 0:
        raise ValueError("Turn size must be a positive integer.")
    if config.trials <= 0:
        raise ValueError("Trials must be a positive integer.")
    if not config.tutor_prompts:
        raise ValueError("Must select at least one tutor prompt.")
    if not config.student_personas:
        raise ValueError("Must select at least one student persona.")
    if not config.course_exercises:
        raise ValueError("Must select at least one course/exercise combination.")

    available_tutor_prompts = set(_discover_tutor_prompts())
    available_personas = set(list_personas())
    available_courses = set(_discover_courses())

    for tutor_prompt in config.tutor_prompts:
        if tutor_prompt not in available_tutor_prompts:
            raise ValueError(f"Unknown tutor prompt: {tutor_prompt}")

    for persona in config.student_personas:
        if persona not in available_personas:
            raise ValueError(f"Unknown student persona: {persona}")
        persona_type = _parse_persona_name(persona)
        if persona_type not in _RAW_SUBDIR_BY_PERSONA_TYPE:
            raise ValueError(
                f"Persona type '{persona_type}' is not supported. "
                f"Supported types: {', '.join(sorted(_RAW_SUBDIR_BY_PERSONA_TYPE))}"
            )

    for course, exercise_num in config.course_exercises:
        if course not in available_courses:
            raise ValueError(f"Unknown course: {course}")
        if exercise_num not in _discover_exercises(course):
            raise ValueError(f"Unknown exercise '{exercise_num}' for course '{course}'")


def _is_retryable_openai_payload_error(error: Exception) -> bool:
    """True if the error looks like a transient OpenAI JSON payload parse failure that is safe to retry."""
    text = str(error).lower()
    return (
        "badrequesterror" in text
        and "could not parse the json body" in text
    )


def _run_conversation(
    config: RunConfig,
    assignment_text: str,
    figures: list | None = None,
) -> list[dict[str, object]]:
    """Run a full multi-turn tutor/student conversation and return the list of exchange dicts.

    *figures* (curriculum images for this exercise, if any) are bound to the
    tutor graph and passed to each student turn so both roles reason over the
    real figure.
    """
    system_prompt = load_system_prompt(
        config.tutor_prompt,
        assignment_override=assignment_text,
    )
    tutor_graph = create_tutor_graph(system_prompt, provider=config.provider, figures=figures)
    student_graph = build_student_graph(prompt_name=config.student_persona)

    transcript_exchanges: list[dict[str, object]] = []
    tutor_messages: list = []
    student_messages: list = [HumanMessage(content=_TUTOR_GREETING)]

    for turn_index in range(config.turn_size):
        student_message = get_next_student_message(
            student_messages,
            assignment=assignment_text,
            turn_size=config.turn_size,
            figures=figures,
            graph=student_graph,
        )
        student_text = (
            student_message.content
            if isinstance(student_message.content, str)
            else str(student_message.content)
        )

        tutor_messages.append(HumanMessage(content=student_text))
        tutor_error: Exception | None = None
        tutor_text = ""
        for attempt in range(1, _TUTOR_CALL_MAX_RETRIES + 2):
            try:
                tutor_messages, tutor_text = get_tutor_reply(tutor_messages, graph=tutor_graph)
                tutor_error = None
                break
            except Exception as error:  # noqa: BLE001
                tutor_error = error
                if _is_retryable_openai_payload_error(error) and attempt < _TUTOR_CALL_MAX_RETRIES + 1:
                    # Rebuild graph before retrying in case model/client state is corrupted.
                    tutor_graph = create_tutor_graph(system_prompt, provider=config.provider, figures=figures)
                    print(
                        "[Warn] transient tutor API payload error; "
                        f"retrying turn={turn_index + 1} attempt={attempt}/{_TUTOR_CALL_MAX_RETRIES + 1}"
                    )
                    continue
                break
        if tutor_error is not None:
            raise RuntimeError(
                "Tutor call failed "
                f"(turn={turn_index + 1}, persona={config.student_persona}, "
                f"course={config.course}, exercise={config.exercise_number}). "
                f"Last error: {tutor_error}"
            ) from tutor_error

        tutor_reasoning = ""
        last_msg = tutor_messages[-1] if tutor_messages else None
        if isinstance(last_msg, AIMessage):
            raw_content = (
                last_msg.content
                if isinstance(last_msg.content, str)
                else str(last_msg.content)
            )
            parsed_reasoning, _ = parse_tutor_response(raw_content)
            tutor_reasoning = (
                parsed_reasoning.strip()
                if isinstance(parsed_reasoning, str) and parsed_reasoning.strip()
                else ""
            )

        student_messages.append(student_message)
        student_messages.append(HumanMessage(content=tutor_text))
        transcript_exchanges.append(
            {
                "turn": turn_index + 1,
                "student": student_text,
                "tutor": tutor_text,
                "pedagogical_reasoning": tutor_reasoning,
            }
        )

    return transcript_exchanges


def _save_raw_transcript(
    config: RunConfig,
    exchanges: list[dict[str, object]],
    output_suffix: str = "raw",
    figure_names: list[str] | None = None,
) -> tuple[str, Path]:
    """Serialize and save a raw transcript JSON; returns (transcript_name, output_path).

    The stored ``context``/``exercise`` are kept lean for the judge (which grades
    tutor behavior per the rubric): context = course.txt, exercise = the problem
    prompt. The full course material the tutor saw is reconstructable from the
    course folder — no need to inline the lecture corpus into every transcript.
    """
    output_dir = _TRANSCRIPTS_DIR / config.persona_type / f"{config.persona_type}_{output_suffix}"
    output_dir.mkdir(parents=True, exist_ok=True)

    course_path = _CURRICULUM_DIR / config.course / "course.txt"
    context_text = (
        course_path.read_text(encoding="utf-8").strip() if course_path.exists() else ""
    )
    exercise_text = (
        "Exercise:\n"
        + exercise_path(config.course, config.exercise_number).read_text(encoding="utf-8").strip()
        + "\n\nRun configuration:\n- Planned conversation length: "
        + f"{config.turn_size} student+tutor exchanges."
    )

    # Protect transcript numbering + write as one critical section to avoid
    # duplicate filenames when raw generation runs in parallel.
    with _SAVE_LOCK:
        transcript_num = _next_transcript_number(output_dir)
        transcript_name = f"transcript_{transcript_num}"
        transcript_path = output_dir / f"{transcript_name}.json"

        payload = {
            "tutor_provider": config.provider,
            "tutor_prompt": config.tutor_prompt,
            "student_persona": config.student_persona,
            "course": config.course,
            "exercise_number": config.exercise_number,
            # Filenames of curriculum figures attached to this run (empty when
            # the exercise has none). The judge re-resolves these to re-attach
            # the images at grading time.
            "figures": figure_names or [],
            "turn_size": config.turn_size,
            "context": context_text,
            "exercise": exercise_text,
            "turns": len(exchanges),
            "exchanges": exchanges,
        }
        transcript_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return transcript_name, transcript_path


def _iter_runs(bundle_config: BundleConfig):
    """Yield (RunConfig, trial_number) for every combination in the bundle config matrix."""
    for tutor_prompt in bundle_config.tutor_prompts:
        for persona_name in bundle_config.student_personas:
            persona_type = _parse_persona_name(persona_name)
            for course, exercise_number in bundle_config.course_exercises:
                for trial in range(1, bundle_config.trials + 1):
                    config = RunConfig(
                        tutor_prompt=tutor_prompt,
                        persona_type=persona_type,
                        course=course,
                        exercise_number=exercise_number,
                        turn_size=bundle_config.turn_size,
                        provider=bundle_config.provider,
                    )
                    yield config, trial


def _get_interactive_config() -> BundleConfig:
    """Get bundle configuration through interactive CLI prompts."""
    print("=== Raw Transcript Generation Configuration ===")

    # Tutor provider
    provider = prompt_single_selection(
        "Tutor provider",
        ["gpt", "claude"],
        required=True,
    )

    # Tutor prompts
    available_tutor_prompts = _discover_tutor_prompts()
    selected_tutor_prompts = prompt_numbered_selection(
        "Tutor prompts",
        available_tutor_prompts,
        allow_empty=True,
        empty_means_all=True,
    )
    
    # Student personas
    available_personas = list_personas()
    selected_personas = prompt_numbered_selection(
        "Student personas",
        available_personas,
        allow_empty=True,
        empty_means_all=True,
    )
    
    # Course/exercise combinations
    available_courses = _discover_courses()
    if not available_courses:
        raise RuntimeError("No courses found in curriculum directory")
    
    course_exercises = []
    for course in available_courses:
        exercises = _discover_exercises(course)
        if exercises:
            course_exercises.extend((course, ex) for ex in exercises)
    
    course_exercise_labels = [f"{course}/exercise_{ex}" for course, ex in course_exercises]
    selected_indices = prompt_numbered_selection(
        "Course/exercise combinations",
        course_exercise_labels,
        allow_empty=True,
        empty_means_all=True,
    )
    selected_course_exercises = [
        course_exercises[course_exercise_labels.index(label)]
        for label in selected_indices
    ]
    
    # Turn size
    turn_size = prompt_integer(
        "Turn size (student+tutor exchanges per conversation)",
        min_value=1,
        max_value=50,
    )
    if turn_size is None:
        turn_size = DEFAULT_TURN_SIZE
    
    # Trials
    trials = prompt_integer(
        "Number of trials per configuration",
        min_value=1,
        max_value=100,
    )
    if trials is None:
        trials = DEFAULT_TRIALS
    
    return BundleConfig(
        provider=provider,
        tutor_prompts=selected_tutor_prompts,
        student_personas=selected_personas,
        course_exercises=selected_course_exercises,
        turn_size=turn_size,
        trials=trials,
    )


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate raw (unjudged) tutor/student transcripts",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (default)
  python -m internal_testing.run_transcript
  
  # Command-line mode
  python -m internal_testing.run_transcript --tutor tutor_03 --personas clueless chaotic --course philosophy --exercise 01 --turn-size 10 --trials 2
        """,
    )
    
    parser.add_argument(
        "--provider",
        choices=["gpt", "claude"],
        default="gpt",
        help="Tutor LLM provider to use: gpt (default) or claude",
    )
    parser.add_argument(
        "--tutor",
        nargs="+",
        help="Tutor prompt names (from tutor/prompts/*.txt)",
    )
    parser.add_argument(
        "--personas",
        nargs="+",
        help="Student persona names (from students/personas/*.txt)",
    )
    parser.add_argument(
        "--course",
        help="Course name (from curriculum/ directories)",
    )
    parser.add_argument(
        "--exercise",
        nargs="+",
        help="Exercise numbers (non-padded, e.g., 1 2)",
    )
    parser.add_argument(
        "--turn-size",
        type=int,
        default=DEFAULT_TURN_SIZE,
        help=f"Number of student+tutor exchanges per conversation (default: {DEFAULT_TURN_SIZE})",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=DEFAULT_TRIALS,
        help=f"Number of trials per configuration (default: {DEFAULT_TRIALS})",
    )
    parser.add_argument(
        "--output-suffix",
        default="raw",
        help="Output folder suffix: transcripts/<type>/<type>_{suffix}/ (default: raw)",
    )
    parser.add_argument(
        "--yes", "-y",
        action="store_true",
        help="Skip confirmation prompt.",
    )

    return parser.parse_args()


def _get_config_from_args(args: argparse.Namespace) -> BundleConfig:
    """Convert command-line arguments to BundleConfig."""
    tutor_prompts = args.tutor or DEFAULT_TUTOR_PROMPTS
    student_personas = args.personas or DEFAULT_STUDENT_PERSONAS

    if args.course and args.exercise:
        course_exercises = [(args.course, ex) for ex in args.exercise]
    else:
        course_exercises = DEFAULT_COURSE_EXERCISES

    return BundleConfig(
        provider=args.provider,
        tutor_prompts=tutor_prompts,
        student_personas=student_personas,
        course_exercises=course_exercises,
        turn_size=args.turn_size,
        trials=args.trials,
        output_suffix=args.output_suffix,
    )


def _run_bundle(bundle_config: BundleConfig, yes: bool = False) -> int:
    """Run the bundle generation with the given configuration."""
    try:
        _validate_bundle_config(bundle_config)
    except (RuntimeError, ValueError) as error:
        print(f"Configuration error: {error}")
        return 1

    # Show summary and get confirmation
    persona_groups = group_personas_by_type(bundle_config.student_personas)
    total_combinations = (
        len(bundle_config.tutor_prompts) *
        len(bundle_config.student_personas) *
        len(bundle_config.course_exercises) *
        bundle_config.trials
    )
    
    summary_lines = [
        f"Will generate {total_combinations} raw transcripts:",
        f"  • Tutor provider: {bundle_config.provider.upper()}",
        f"  • {len(bundle_config.tutor_prompts)} tutor prompt(s): {', '.join(bundle_config.tutor_prompts)}",
        f"  • {len(bundle_config.student_personas)} student persona(s) across {len(persona_groups)} type(s)",
    ]
    for persona_type, personas in persona_groups.items():
        summary_lines.append(f"    - {persona_type}: {', '.join(personas)}")
    
    summary_lines.extend([
        f"  • {len(bundle_config.course_exercises)} course/exercise combination(s): {', '.join(f'{c}/{e}' for c, e in bundle_config.course_exercises)}",
        f"  • {bundle_config.turn_size} turns per conversation",
        f"  • {bundle_config.trials} trial(s) per configuration",
    ])
    
    if not yes and not confirm_proceed("\n".join(summary_lines)):
        print("Cancelled.")
        return 0

    try:
        failed_runs = 0
        runs = list(_iter_runs(bundle_config))
        total_runs = len(runs)
        print(f"[Raw Bundle] Running in parallel with {PARALLEL_WORKERS} workers. Tutor provider: {bundle_config.provider.upper()}")

        def _run_one(config: RunConfig, trial: int) -> dict[str, object]:
            """Run one config/trial end to end (assignment, conversation, save) and
            return a result dict with ok/trial/config plus path or failure reason."""
            assignment_text = _build_assignment_text(
                config.course,
                config.exercise_number,
                config.turn_size,
            )
            figures = discover_figures(config.course, config.exercise_number)
            try:
                exchanges = _run_conversation(config, assignment_text, figures)
            except RuntimeError as error:
                return {
                    "ok": False,
                    "trial": trial,
                    "config": config,
                    "reason": str(error),
                }
            _, transcript_path = _save_raw_transcript(
                config,
                exchanges,
                output_suffix=bundle_config.output_suffix,
                figure_names=figure_filenames(figures),
            )
            return {
                "ok": True,
                "trial": trial,
                "config": config,
                "path": transcript_path,
            }

        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as pool:
            futures = {pool.submit(_run_one, config, trial): (config, trial) for config, trial in runs}
            completed = 0
            for future in as_completed(futures):
                completed += 1
                result = future.result()
                config = result["config"]
                trial = int(result["trial"])
                if result["ok"]:
                    transcript_path = Path(result["path"])
                    print(
                        "[Raw Bundle] "
                        f"[{completed}/{total_runs}] "
                        f"trial={trial}/{bundle_config.trials} "
                        f"tutor={config.tutor_prompt} "
                        f"persona={config.student_persona} "
                        f"course={config.course} "
                        f"exercise={config.exercise_number} "
                        f"turns={config.turn_size} "
                        f"saved={transcript_path.relative_to(_REPO_ROOT)}"
                    )
                else:
                    failed_runs += 1
                    reason = result["reason"]
                    print(
                        "[Run Failed] "
                        f"[{completed}/{total_runs}] "
                        f"trial={trial}/{bundle_config.trials} "
                        f"tutor={config.tutor_prompt} "
                        f"persona={config.student_persona} "
                        f"course={config.course} "
                        f"exercise={config.exercise_number} "
                        f"reason={reason}"
                    )
        if failed_runs:
            print(f"[Raw Bundle] completed with {failed_runs} failed run(s).")
    except KeyboardInterrupt:
        print("\nRaw bundle interrupted.")
        return 130
    except FileNotFoundError as error:
        print(f"Missing curriculum file: {error.filename}")
        return 1

    return 0


def main() -> int:
    """CLI entry point: get config via interactive prompts or args, then run bundle generation."""
    args = _parse_args()
    
    # Determine if we should use interactive mode
    use_interactive = not any([
        args.tutor,
        args.personas,
        args.course,
        args.exercise,
    ])
    
    try:
        if use_interactive:
            bundle_config = _get_interactive_config()
        else:
            bundle_config = _get_config_from_args(args)
        
        return _run_bundle(bundle_config, yes=args.yes)
        
    except (RuntimeError, ValueError) as error:
        print(f"Error: {error}")
        return 1
    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
