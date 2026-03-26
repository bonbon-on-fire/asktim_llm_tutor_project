"""
Batch runner that generates raw (unjudged) tutor/student transcripts.

Edit the config lists in this file, then run:
    python -m ui.run_ui_raw
"""

from __future__ import annotations

import json
import os
import re
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

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TUTOR_PROMPTS_DIR = _REPO_ROOT / "tutor" / "prompts"
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"

_TUTOR_GREETING = "Hi. What would you like to work on today?"
_RAW_SUBDIR_BY_PERSONA_TYPE: dict[str, str] = {
    "chaotic": "chaotic_raw",
    "chitchat": "chitchat_raw",
    "clueless": "clueless_raw",
}
_TUTOR_CALL_MAX_RETRIES = 2

# ---------------------------------------------------------------------------
# Batch config (edit these directly)
# ---------------------------------------------------------------------------

# Which tutor prompts to run (from tutor/prompts/*.txt, without extension).
TUTOR_PROMPTS: list[str] = ["tutor_04"]

# Which student personas to run (from students/personas/*.txt, without extension).
STUDENT_PERSONAS: list[str] = ["chitchat_01", "chitchat_02", "chitchat_03"]

# Which course/exercise combinations to run.
# Exercise numbers should be zero-padded strings like "01".
COURSE_EXERCISES: list[tuple[str, str]] = [("philosophy", "01"), ("urban_studies", "01"), ("urban_studies", "02"), ("urban_studies", "03")]

# Turn size per conversation (student+tutor exchanges).
TURN_SIZE: int = 10

# How many trials for each matrix combination.
TRIALS: int = 2


@dataclass(frozen=True)
class RunConfig:
    tutor_prompt: str
    persona_type: str
    persona_version: str
    course: str
    exercise_number: str
    turn_size: int

    @property
    def student_persona(self) -> str:
        return f"{self.persona_type}_{self.persona_version}"


def _require_openai_api_key() -> None:
    if os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY"):
        return
    raise RuntimeError(
        "OPENAI_API_KEY (or OPENAI_KEY) environment variable is required but not set."
    )


def _discover_stems(directory: Path, suffix: str) -> list[str]:
    if not directory.exists():
        return []
    return sorted(path.stem for path in directory.glob(f"*{suffix}"))


def _discover_tutor_prompts() -> list[str]:
    return _discover_stems(_TUTOR_PROMPTS_DIR, ".txt")


def _discover_courses() -> list[str]:
    if not _CURRICULUM_DIR.exists():
        return []
    return sorted(path.name for path in _CURRICULUM_DIR.iterdir() if path.is_dir())


def _discover_exercises(course: str) -> list[str]:
    course_dir = _CURRICULUM_DIR / course
    if not course_dir.exists():
        return []
    exercise_nums: list[str] = []
    for path in sorted(course_dir.glob("exercise_*.txt")):
        match = re.match(r"^exercise_(\d{2})\.txt$", path.name)
        if match:
            exercise_nums.append(match.group(1))
    return exercise_nums


def _parse_persona_name(prompt_name: str) -> tuple[str, str]:
    match = re.match(r"^([a-zA-Z0-9]+)_(\d{2})$", prompt_name)
    if not match:
        raise ValueError(
            f"Persona '{prompt_name}' must use '<type>_<NN>' format (example: chaotic_01)."
        )
    return match.group(1), match.group(2)


def _load_course_context(course: str) -> str:
    course_dir = _CURRICULUM_DIR / course
    return (course_dir / "course.txt").read_text(encoding="utf-8").strip()


def _build_assignment_text(course: str, exercise_number: str, turn_size: int) -> str:
    course_dir = _CURRICULUM_DIR / course
    course_text = _load_course_context(course)
    exercise_text = (
        course_dir / f"exercise_{exercise_number}.txt"
    ).read_text(encoding="utf-8").strip()
    return (
        "Course context:\n"
        f"{course_text}\n\n"
        "Exercise:\n"
        f"{exercise_text}\n\n"
        "Run configuration:\n"
        f"- Planned conversation length: {turn_size} student+tutor exchanges."
    )


def _next_transcript_number(output_dir: Path) -> str:
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


def _validate_manual_config() -> None:
    _require_openai_api_key()
    if TURN_SIZE <= 0:
        raise ValueError("TURN_SIZE must be a positive integer.")
    if TRIALS <= 0:
        raise ValueError("TRIALS must be a positive integer.")
    if not TUTOR_PROMPTS:
        raise ValueError("TUTOR_PROMPTS must contain at least one item.")
    if not STUDENT_PERSONAS:
        raise ValueError("STUDENT_PERSONAS must contain at least one item.")
    if not COURSE_EXERCISES:
        raise ValueError("COURSE_EXERCISES must contain at least one item.")

    available_tutor_prompts = set(_discover_tutor_prompts())
    available_personas = set(list_personas())
    available_courses = set(_discover_courses())

    for tutor_prompt in TUTOR_PROMPTS:
        if tutor_prompt not in available_tutor_prompts:
            raise ValueError(f"Unknown tutor prompt: {tutor_prompt}")

    for persona in STUDENT_PERSONAS:
        if persona not in available_personas:
            raise ValueError(f"Unknown student persona: {persona}")
        persona_type, _ = _parse_persona_name(persona)
        if persona_type not in _RAW_SUBDIR_BY_PERSONA_TYPE:
            raise ValueError(
                f"Persona type '{persona_type}' is not supported. "
                f"Supported types: {', '.join(sorted(_RAW_SUBDIR_BY_PERSONA_TYPE))}"
            )

    for course, exercise_num in COURSE_EXERCISES:
        if course not in available_courses:
            raise ValueError(f"Unknown course: {course}")
        if exercise_num not in _discover_exercises(course):
            raise ValueError(f"Unknown exercise '{exercise_num}' for course '{course}'")


def _is_retryable_openai_payload_error(error: Exception) -> bool:
    text = str(error).lower()
    return (
        "badrequesterror" in text
        and "could not parse the json body" in text
    )


def _run_conversation(config: RunConfig, assignment_text: str) -> list[dict[str, object]]:
    system_prompt = load_system_prompt(
        config.tutor_prompt,
        assignment_override=assignment_text,
    )
    tutor_graph = create_tutor_graph(system_prompt)
    student_graph = build_student_graph(prompt_name=config.student_persona)

    transcript_exchanges: list[dict[str, object]] = []
    tutor_messages: list = []
    student_messages: list = [HumanMessage(content=_TUTOR_GREETING)]

    for turn_index in range(config.turn_size):
        student_message = get_next_student_message(
            student_messages,
            assignment=assignment_text,
            turn_size=config.turn_size,
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
                if _is_retryable_openai_payload_error(error) and attempt <= _TUTOR_CALL_MAX_RETRIES:
                    # Rebuild graph before retrying in case model/client state is corrupted.
                    tutor_graph = create_tutor_graph(system_prompt)
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
    context_text: str,
    assignment_text: str,
    exchanges: list[dict[str, object]],
) -> tuple[str, Path]:
    raw_subdir = _RAW_SUBDIR_BY_PERSONA_TYPE[config.persona_type]
    output_dir = _TRANSCRIPTS_DIR / config.persona_type / raw_subdir
    output_dir.mkdir(parents=True, exist_ok=True)

    transcript_num = _next_transcript_number(output_dir)
    transcript_name = f"transcript_{transcript_num}"
    transcript_path = output_dir / f"{transcript_name}.json"

    payload = {
        "tutor_prompt": config.tutor_prompt,
        "student_persona": config.student_persona,
        "course": config.course,
        "exercise_number": config.exercise_number,
        "turn_size": config.turn_size,
        "context": context_text,
        "exercise": assignment_text,
        "turns": len(exchanges),
        "exchanges": exchanges,
    }
    transcript_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return transcript_name, transcript_path


def _iter_runs():
    for tutor_prompt in TUTOR_PROMPTS:
        for persona_name in STUDENT_PERSONAS:
            persona_type, persona_version = _parse_persona_name(persona_name)
            for course, exercise_number in COURSE_EXERCISES:
                for trial in range(1, TRIALS + 1):
                    config = RunConfig(
                        tutor_prompt=tutor_prompt,
                        persona_type=persona_type,
                        persona_version=persona_version,
                        course=course,
                        exercise_number=exercise_number,
                        turn_size=TURN_SIZE,
                    )
                    yield config, trial


def main() -> int:
    try:
        _validate_manual_config()
    except (RuntimeError, ValueError) as error:
        print(str(error))
        return 1

    try:
        failed_runs = 0
        for config, trial in _iter_runs():
            assignment_text = _build_assignment_text(
                config.course,
                config.exercise_number,
                config.turn_size,
            )
            context_text = _load_course_context(config.course)
            try:
                exchanges = _run_conversation(config, assignment_text)
            except RuntimeError as error:
                failed_runs += 1
                print(
                    "[Run Failed] "
                    f"trial={trial}/{TRIALS} "
                    f"tutor={config.tutor_prompt} "
                    f"persona={config.student_persona} "
                    f"course={config.course} "
                    f"exercise={config.exercise_number} "
                    f"reason={error}"
                )
                continue
            _, transcript_path = _save_raw_transcript(
                config,
                context_text,
                assignment_text,
                exchanges,
            )
            print(
                "[Raw Batch] "
                f"trial={trial}/{TRIALS} "
                f"tutor={config.tutor_prompt} "
                f"persona={config.student_persona} "
                f"course={config.course} "
                f"exercise={config.exercise_number} "
                f"turns={config.turn_size} "
                f"saved={transcript_path.relative_to(_REPO_ROOT)}"
            )
        if failed_runs:
            print(f"[Raw Batch] completed with {failed_runs} failed run(s).")
    except KeyboardInterrupt:
        print("\nRaw batch interrupted.")
        return 130
    except FileNotFoundError as error:
        print(f"Missing curriculum file: {error.filename}")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
