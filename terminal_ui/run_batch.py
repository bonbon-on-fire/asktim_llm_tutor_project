"""
Batch automation runner for tutor-vs-student evaluations.

Edit the lists in this file, then run:
    python -m terminal_ui.run_batch
"""

from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from langchain_core.messages import HumanMessage

from judge import JudgeError, judge_transcript
from students.run_student import build_graph as build_student_graph
from students.run_student import get_next_student_message, list_personas
from tutor.run_tutor import create_tutor_graph, get_tutor_reply, load_system_prompt

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TUTOR_PROMPTS_DIR = _REPO_ROOT / "tutor" / "prompts"
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_JUDGE_PROMPTS_DIR = _REPO_ROOT / "judge" / "prompts"
_JUDGE_RUBRICS_DIR = _REPO_ROOT / "judge" / "rubrics"
_TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"
_RESULTS_CSV_PATH = _TRANSCRIPTS_DIR / "transcripts_compiled.csv"

_TUTOR_GREETING = "Hi. What would you like to work on today?"

# ---------------------------------------------------------------------------
# Batch config (edit these directly)
# ---------------------------------------------------------------------------

# Which tutor prompts to run (from tutor/prompts/*.txt, without extension).
TUTOR_PROMPTS: list[str] = ["tutor_01"]

# Which student personas to run (from students/personas/*.txt, without extension).
STUDENT_PERSONAS: list[str] = ["chitchat_01","chitchat_02","chitchat_03"]

# Which course/exercise combinations to run.
# Exercise numbers should be zero-padded strings like "01".
COURSE_EXERCISES: list[tuple[str, str]] = [("philosophy", "01"), ("urban_studies", "01"), ("urban_studies", "02"), ("urban_studies", "03")]

# Turn size per conversation (student+tutor exchanges).
TURN_SIZE: int = 10

# Judge prompt/rubric versions.
JUDGE_PROMPTS: list[str] = ["judge_02"]
JUDGE_RUBRICS: list[str] = ["rubric_02"]

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


def _discover_judge_prompts() -> list[str]:
    return _discover_stems(_JUDGE_PROMPTS_DIR, ".txt")


def _discover_judge_rubrics() -> list[str]:
    return _discover_stems(_JUDGE_RUBRICS_DIR, ".md")


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


def _build_assignment_text(course: str, exercise_number: str, turn_size: int) -> str:
    course_dir = _CURRICULUM_DIR / course
    course_text = (course_dir / "course.txt").read_text(encoding="utf-8").strip()
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


def _next_transcript_number(persona_dir: Path) -> str:
    used_numbers: set[int] = set()
    if persona_dir.exists():
        for path in persona_dir.glob("transcript_*.json"):
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
    if not JUDGE_PROMPTS:
        raise ValueError("JUDGE_PROMPTS must contain at least one item.")
    if not JUDGE_RUBRICS:
        raise ValueError("JUDGE_RUBRICS must contain at least one item.")

    available_tutor_prompts = set(_discover_tutor_prompts())
    available_personas = set(list_personas())
    available_courses = set(_discover_courses())
    available_judge_prompts = set(_discover_judge_prompts())
    available_judge_rubrics = set(_discover_judge_rubrics())

    for tutor_prompt in TUTOR_PROMPTS:
        if tutor_prompt not in available_tutor_prompts:
            raise ValueError(f"Unknown tutor prompt: {tutor_prompt}")
    for persona in STUDENT_PERSONAS:
        if persona not in available_personas:
            raise ValueError(f"Unknown student persona: {persona}")
        _parse_persona_name(persona)
    for course, exercise_num in COURSE_EXERCISES:
        if course not in available_courses:
            raise ValueError(f"Unknown course: {course}")
        if exercise_num not in _discover_exercises(course):
            raise ValueError(f"Unknown exercise '{exercise_num}' for course '{course}'")
    for judge_prompt in JUDGE_PROMPTS:
        if judge_prompt not in available_judge_prompts:
            raise ValueError(f"Unknown judge prompt: {judge_prompt}")
    for judge_rubric in JUDGE_RUBRICS:
        if judge_rubric not in available_judge_rubrics:
            raise ValueError(f"Unknown judge rubric: {judge_rubric}")


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
        tutor_messages, tutor_text = get_tutor_reply(tutor_messages, graph=tutor_graph)

        student_messages.append(student_message)
        student_messages.append(HumanMessage(content=tutor_text))
        transcript_exchanges.append(
            {"turn": turn_index + 1, "student": student_text, "tutor": tutor_text}
        )

    return transcript_exchanges


def _save_transcript(
    config: RunConfig,
    judge_prompt: str,
    judge_rubric: str,
    assignment_text: str,
    exchanges: list[dict[str, object]],
) -> tuple[str, Path]:
    persona_dir = _TRANSCRIPTS_DIR / config.persona_type
    persona_dir.mkdir(parents=True, exist_ok=True)
    transcript_num = _next_transcript_number(persona_dir)
    transcript_name = f"transcript_{transcript_num}"
    transcript_path = persona_dir / f"{transcript_name}.json"

    payload = {
        "tutor_prompt": config.tutor_prompt,
        "student_persona": config.student_persona,
        "course": config.course,
        "exercise_number": config.exercise_number,
        "turn_size": config.turn_size,
        "exercise": assignment_text,
        "judge_prompt": judge_prompt,
        "judge_rubric": judge_rubric,
        "turns": len(exchanges),
        "exchanges": exchanges,
    }
    transcript_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return transcript_name, transcript_path


def _extract_deductions_text(transcript_payload: dict) -> str:
    grade = transcript_payload.get("grade")
    if not isinstance(grade, dict):
        return ""
    sections = grade.get("sections")
    if not isinstance(sections, dict):
        return ""

    lines: list[str] = []
    for section_id in sorted(sections.keys()):
        section_payload = sections.get(section_id)
        if not isinstance(section_payload, dict):
            continue
        criteria = section_payload.get("criteria")
        if not isinstance(criteria, dict):
            continue
        for criterion_id in sorted(criteria.keys()):
            criterion_payload = criteria.get(criterion_id)
            if not isinstance(criterion_payload, dict):
                continue
            deductions = criterion_payload.get("deductions", [])
            if not isinstance(deductions, list):
                continue
            for deduction in deductions:
                if not isinstance(deduction, dict):
                    continue
                reason = str(deduction.get("reason", "")).strip()
                if not reason:
                    continue
                lines.append(f"{section_id}/{criterion_id}: {reason}")
    return "\n".join(lines)


def _append_results_csv(
    *,
    config: RunConfig,
    judge_prompt: str,
    judge_rubric: str,
    transcript_name: str,
    transcript_path: Path,
) -> None:
    transcript_payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    deductions_text = _extract_deductions_text(transcript_payload)

    _RESULTS_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    should_write_header = (
        (not _RESULTS_CSV_PATH.exists())
        or _RESULTS_CSV_PATH.stat().st_size == 0
    )
    with _RESULTS_CSV_PATH.open("a", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        if should_write_header:
            writer.writerow(
                [
                    "tutor_prompt",
                    "student_persona",
                    "course",
                    "exercise_number",
                    "judge_prompt",
                    "judge_rubric",
                    "transcript_name",
                    "deductions",
                ]
            )
        writer.writerow(
            [
                config.tutor_prompt,
                config.student_persona,
                config.course,
                config.exercise_number,
                judge_prompt,
                judge_rubric,
                transcript_name,
                deductions_text,
            ]
        )


def _iter_runs():
    for tutor_prompt in TUTOR_PROMPTS:
        for persona_name in STUDENT_PERSONAS:
            persona_type, persona_version = _parse_persona_name(persona_name)
            for course, exercise_number in COURSE_EXERCISES:
                for judge_prompt in JUDGE_PROMPTS:
                    for judge_rubric in JUDGE_RUBRICS:
                        for trial in range(1, TRIALS + 1):
                            config = RunConfig(
                                tutor_prompt=tutor_prompt,
                                persona_type=persona_type,
                                persona_version=persona_version,
                                course=course,
                                exercise_number=exercise_number,
                                turn_size=TURN_SIZE,
                            )
                            yield config, judge_prompt, judge_rubric, trial


def main() -> int:
    try:
        _validate_manual_config()
    except (RuntimeError, ValueError) as error:
        print(str(error))
        return 1

    try:
        for config, judge_prompt, judge_rubric, trial in _iter_runs():
            assignment_text = _build_assignment_text(
                config.course,
                config.exercise_number,
                config.turn_size,
            )
            exchanges = _run_conversation(config, assignment_text)
            transcript_name, transcript_path = _save_transcript(
                config,
                judge_prompt,
                judge_rubric,
                assignment_text,
                exchanges,
            )
            relative_stem = f"{config.persona_type}/{transcript_name}"
            result = judge_transcript(
                relative_stem,
                prompt_name=judge_prompt,
                rubric_name=judge_rubric,
            )
            _append_results_csv(
                config=config,
                judge_prompt=judge_prompt,
                judge_rubric=judge_rubric,
                transcript_name=transcript_name,
                transcript_path=transcript_path,
            )
            print(
                "[Batch] "
                f"trial={trial}/{TRIALS} "
                f"tutor={config.tutor_prompt} "
                f"persona={config.student_persona} "
                f"course={config.course} "
                f"exercise={config.exercise_number} "
                f"judge={judge_prompt} "
                f"rubric={judge_rubric} "
                f"score={result.total_score}/{result.max_score} "
                f"transcript={transcript_path.relative_to(_REPO_ROOT)}"
            )
    except KeyboardInterrupt:
        print("\nBatch interrupted.")
        return 130
    except FileNotFoundError as error:
        print(f"Missing curriculum file: {error.filename}")
        return 1
    except JudgeError as error:
        print(f"Judge failed: {error}")
        return 1

    print(f"[Results] appended: {_RESULTS_CSV_PATH.relative_to(_REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
