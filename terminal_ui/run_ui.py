"""Terminal UI runner based on terminal_ui/README.md."""

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
from students.run_student import get_next_student_message
from tutor.run_tutor import create_tutor_graph, get_tutor_reply, load_system_prompt

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TUTOR_PROMPTS_DIR = _REPO_ROOT / "tutor" / "prompts"
_PERSONAS_DIR = _REPO_ROOT / "students" / "personas"
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_JUDGE_PROMPTS_DIR = _REPO_ROOT / "judge" / "prompts"
_JUDGE_RUBRICS_DIR = _REPO_ROOT / "judge" / "rubrics"
_TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"
_RESULTS_CSV_PATH = _TRANSCRIPTS_DIR / "transcripts_compiled.csv"

_PERSONA_TYPES: tuple[str, ...] = ("chaotic", "chitchat", "clueless")
_TUTOR_GREETING = "Hi. What would you like to work on today?"


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


def _discover_persona_versions(persona_type: str) -> list[str]:
    versions: list[str] = []
    for path in sorted(_PERSONAS_DIR.glob(f"{persona_type}_*.txt")):
        match = re.match(rf"^{re.escape(persona_type)}_(\d{{2}})\.txt$", path.name)
        if match:
            versions.append(match.group(1))
    return versions


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


def _discover_judge_prompts() -> list[str]:
    return _discover_stems(_JUDGE_PROMPTS_DIR, ".txt")


def _discover_judge_rubrics() -> list[str]:
    return _discover_stems(_JUDGE_RUBRICS_DIR, ".md")


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


def _prompt(label: str) -> str:
    return input(label).strip()


def _prompt_choice(label: str, options: list[str]) -> str:
    if not options:
        raise RuntimeError(f"No options available for: {label}")
    if len(options) == 1:
        print(f"{label}: {options[0]} (only option)")
        return options[0]
    joined = ", ".join(options)
    while True:
        answer = _prompt(f"{label} ({joined}): ")
        if answer in options:
            return answer
        print(f"  Please enter one of: {joined}")


def _prompt_number(label: str, options: list[str]) -> str:
    if not options:
        raise RuntimeError(f"No options available for: {label}")
    if len(options) == 1:
        print(f"{label}: {options[0]} (only option)")
        return options[0]
    num_range = f"{options[0]}..{options[-1]}"
    while True:
        answer = _prompt(f"{label} ({num_range}): ").lstrip("0") or "0"
        padded = f"{int(answer):02d}" if answer.isdigit() else ""
        if padded in options:
            return padded
        print(f"  Please enter a number between {options[0]} and {options[-1]}")


def _prompt_turn_size() -> int:
    while True:
        answer = _prompt("Number of turns (student+tutor exchanges): ")
        if answer.isdigit() and int(answer) > 0:
            return int(answer)
        print("  Please enter a positive integer.")


def _prompt_versioned_name(label: str, prefix: str, options: list[str]) -> str:
    versions: list[str] = []
    for opt in options:
        match = re.match(rf"^{re.escape(prefix)}_(\d{{2}})$", opt)
        if not match:
            return _prompt_choice(label, options)
        versions.append(match.group(1))
    return f"{prefix}_{_prompt_number(f'{label} version', sorted(versions))}"


def _collect_run_config() -> RunConfig:
    tutor_prompt = _prompt_choice("Tutor prompt", _discover_tutor_prompts())
    persona_type = _prompt_choice("Student persona type", list(_PERSONA_TYPES))
    persona_version = _prompt_number(
        f"  {persona_type} version",
        _discover_persona_versions(persona_type),
    )
    course = _prompt_choice("Course", _discover_courses())
    exercise_number = _prompt_number(
        f"  Exercise in {course}",
        _discover_exercises(course),
    )
    turn_size = _prompt_turn_size()
    return RunConfig(
        tutor_prompt=tutor_prompt,
        persona_type=persona_type,
        persona_version=persona_version,
        course=course,
        exercise_number=exercise_number,
        turn_size=turn_size,
    )


def _collect_judge_config() -> tuple[str, str]:
    judge_prompt = _prompt_versioned_name(
        "Judge prompt",
        "judge",
        _discover_judge_prompts(),
    )
    judge_rubric = _prompt_versioned_name(
        "Judge rubric",
        "rubric",
        _discover_judge_rubrics(),
    )
    return judge_prompt, judge_rubric


def _run_conversation(config: RunConfig, assignment_text: str) -> list[dict[str, object]]:
    system_prompt = load_system_prompt(
        config.tutor_prompt,
        assignment_override=assignment_text,
    )
    tutor_graph = create_tutor_graph(system_prompt)
    student_graph = build_student_graph(prompt_name=config.student_persona)

    print()
    print(
        f"[Config] tutor={config.tutor_prompt}  "
        f"persona={config.student_persona}  "
        f"course={config.course}  "
        f"exercise={config.exercise_number}  "
        f"turns={config.turn_size}"
    )
    print()
    print(f"[Tutor] {_TUTOR_GREETING}\n")

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
        print(f"[Student] {student_text}\n")

        tutor_messages.append(HumanMessage(content=student_text))
        tutor_messages, tutor_text = get_tutor_reply(tutor_messages, graph=tutor_graph)
        print(f"[Tutor] {tutor_text}\n")

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


def main() -> int:
    try:
        _require_openai_api_key()
        config = _collect_run_config()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 130
    except RuntimeError as error:
        print(str(error))
        return 1

    try:
        assignment_text = _build_assignment_text(
            config.course,
            config.exercise_number,
            config.turn_size,
        )
        exchanges = _run_conversation(config, assignment_text)
    except KeyboardInterrupt:
        print("\nConversation interrupted.")
        return 130
    except FileNotFoundError as error:
        print(f"Missing curriculum file: {error.filename}")
        return 1

    try:
        judge_prompt, judge_rubric = _collect_judge_config()
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. Exiting without saving.")
        return 130

    transcript_name, transcript_path = _save_transcript(
        config,
        judge_prompt,
        judge_rubric,
        assignment_text,
        exchanges,
    )
    print(f"Saved transcript to: {transcript_path.relative_to(_REPO_ROOT)}")

    relative_stem = f"{config.persona_type}/{transcript_name}"
    try:
        result = judge_transcript(
            relative_stem,
            prompt_name=judge_prompt,
            rubric_name=judge_rubric,
        )
    except JudgeError as error:
        print(f"Judge failed: {error}")
        return 1

    print(f"[Judge] total_score={result.total_score}/{result.max_score}")
    _append_results_csv(
        config=config,
        judge_prompt=judge_prompt,
        judge_rubric=judge_rubric,
        transcript_name=transcript_name,
        transcript_path=transcript_path,
    )
    print(f"[Results] appended: {_RESULTS_CSV_PATH.relative_to(_REPO_ROOT)}")
    return 0

