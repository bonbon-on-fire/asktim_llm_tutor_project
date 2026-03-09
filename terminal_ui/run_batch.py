"""
Batch automation runner for tutor-vs-student evaluations.

Runs all selected personas against all selected exercises for N trials each,
then auto-saves transcripts and runs the judge for every conversation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path

from langchain_core.messages import HumanMessage

from judge import JudgeError, judge_transcript
from students.run_student import build_graph as build_student_graph
from students.run_student import get_next_student_message, list_personas
from tutor.run_tutor import create_tutor_graph, get_tutor_reply, load_system_prompt

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TUTOR_PROMPTS_DIR = _REPO_ROOT / "tutor" / "prompts"
_JUDGE_PROMPTS_DIR = _REPO_ROOT / "judge" / "prompts"
_JUDGE_RUBRICS_DIR = _REPO_ROOT / "judge" / "rubrics"
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"


def _discover_tutor_versions() -> list[str]:
    if not _TUTOR_PROMPTS_DIR.exists():
        return []
    return sorted(p.stem for p in _TUTOR_PROMPTS_DIR.glob("*.txt"))


def _discover_judge_versions() -> list[str]:
    if not _JUDGE_PROMPTS_DIR.exists():
        return []
    return sorted(p.stem for p in _JUDGE_PROMPTS_DIR.glob("*.txt"))


def _discover_judge_rubrics() -> list[str]:
    if not _JUDGE_RUBRICS_DIR.exists():
        return []
    return sorted(p.stem for p in _JUDGE_RUBRICS_DIR.glob("*.md"))


def _discover_courses() -> list[str]:
    if not _CURRICULUM_DIR.exists():
        return []
    return sorted(d.name for d in _CURRICULUM_DIR.iterdir() if d.is_dir())


def _discover_exercises(course: str) -> list[str]:
    course_dir = _CURRICULUM_DIR / course
    if not course_dir.exists():
        return []
    numbers: list[str] = []
    for p in sorted(course_dir.glob("exercise_*.txt")):
        m = re.match(r"^exercise_(\d{2})\.txt$", p.name)
        if m:
            numbers.append(m.group(1))
    return numbers


def _load_assignment_text(course: str, exercise_num: str, turn_size: int) -> str:
    course_dir = _CURRICULUM_DIR / course
    course_path = course_dir / "course.txt"
    exercise_path = course_dir / f"exercise_{exercise_num}.txt"

    course_text = course_path.read_text(encoding="utf-8").strip()
    exercise_text = exercise_path.read_text(encoding="utf-8").strip()

    return (
        "Course context:\n"
        f"{course_text}\n\n"
        "Exercise:\n"
        f"{exercise_text}\n\n"
        "Run configuration:\n"
        f"- Planned conversation length: {turn_size} student+tutor exchanges."
    )


def _next_transcript_number(persona_dir: Path) -> str:
    existing: set[int] = set()
    if persona_dir.exists():
        for p in persona_dir.glob("transcript_*.json"):
            m = re.match(r"^transcript_(\d+)\.json$", p.name)
            if m:
                existing.add(int(m.group(1)))
    n = 1
    while n in existing:
        n += 1
    return f"{n:02d}"


def _persona_type_from_prompt_name(prompt_name: str) -> str:
    return prompt_name.split("_", 1)[0] if "_" in prompt_name else "misc"


def _parse_course_exercise(spec: str) -> tuple[str, str]:
    raw = (spec or "").strip()
    if ":" not in raw:
        raise ValueError(
            f"Invalid --course-exercise '{spec}'. Use 'course:exercise_number', e.g. philosophy:01"
        )
    course, exercise_raw = raw.split(":", 1)
    course = course.strip()
    exercise_raw = exercise_raw.strip().lstrip("0") or "0"
    if not course:
        raise ValueError(f"Invalid --course-exercise '{spec}': missing course.")
    if not exercise_raw.isdigit():
        raise ValueError(
            f"Invalid --course-exercise '{spec}': exercise number must be numeric."
        )
    return course, f"{int(exercise_raw):02d}"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Automate runs with explicit config: tutor_prompt x student_personas x "
            "course+exercise list x judge_prompt x judge_rubric x trials."
        )
    )
    parser.add_argument(
        "--turn-size",
        type=int,
        default=10,
        help="Student+tutor exchanges per conversation (default: 10).",
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=1,
        help="Number of trials per persona+exercise pair (default: 1).",
    )
    parser.add_argument(
        "--tutor-prompt",
        type=str,
        required=True,
        help="Tutor prompt version to run (e.g. tutor_01).",
    )
    parser.add_argument(
        "--judge-prompt",
        type=str,
        required=True,
        help="Judge prompt version to use (e.g. judge_01).",
    )
    parser.add_argument(
        "--judge-rubric",
        type=str,
        required=True,
        help="Judge rubric version to use (e.g. rubric_01).",
    )
    parser.add_argument(
        "--student-persona",
        action="append",
        required=True,
        help="Student persona(s) to include. Repeat flag for a list.",
    )
    parser.add_argument(
        "--course-exercise",
        action="append",
        required=True,
        help="Course+exercise pair, e.g. philosophy:01. Repeat flag for a list.",
    )
    return parser.parse_args()


def main() -> int:
    if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")):
        print("OPENAI_API_KEY (or OPENAI_KEY) environment variable is required but not set.")
        return 1

    args = _parse_args()
    if args.turn_size <= 0:
        print("--turn-size must be a positive integer.")
        return 2
    if args.trials <= 0:
        print("--trials must be a positive integer.")
        return 2

    tutor_versions = _discover_tutor_versions()
    judge_versions = _discover_judge_versions()
    judge_rubrics = _discover_judge_rubrics()
    courses = _discover_courses()
    personas = list_personas()

    if not tutor_versions:
        print("No tutor prompts found in tutor/prompts.")
        return 1
    if not judge_versions:
        print("No judge prompts found in judge/prompts.")
        return 1
    if not judge_rubrics:
        print("No judge rubrics found in judge/rubrics.")
        return 1
    if not courses:
        print("No courses found in curriculum/.")
        return 1
    if not personas:
        print("No personas found in students/personas.")
        return 1

    tutor_prompt = args.tutor_prompt
    judge_prompt = args.judge_prompt
    judge_rubric = args.judge_rubric
    if tutor_prompt not in tutor_versions:
        print(f"Unknown tutor prompt: {tutor_prompt}. Available: {tutor_versions}")
        return 2
    if judge_prompt not in judge_versions:
        print(f"Unknown judge prompt: {judge_prompt}. Available: {judge_versions}")
        return 2
    if judge_rubric not in judge_rubrics:
        print(f"Unknown judge rubric: {judge_rubric}. Available: {judge_rubrics}")
        return 2

    wanted_personas = set(args.student_persona)
    unknown = sorted(wanted_personas - set(personas))
    if unknown:
        print(f"Unknown persona(s): {unknown}. Available: {personas}")
        return 2
    personas = [p for p in personas if p in wanted_personas]

    selected_course_exercises: list[tuple[str, str]] = []
    for spec in args.course_exercise:
        try:
            selected_course_exercises.append(_parse_course_exercise(spec))
        except ValueError as e:
            print(str(e))
            return 2

    valid_courses = set(courses)
    for course, exercise_num in selected_course_exercises:
        if course not in valid_courses:
            print(f"Unknown course: {course}. Available: {courses}")
            return 2
        available_exercises = _discover_exercises(course)
        if exercise_num not in available_exercises:
            print(
                f"Unknown exercise '{exercise_num}' for course '{course}'. "
                f"Available: {available_exercises}"
            )
            return 2

    run_specs: list[tuple[str, str, str, int]] = []
    for persona_name in personas:
        for course, exercise_num in selected_course_exercises:
            for trial_num in range(1, args.trials + 1):
                run_specs.append((persona_name, course, exercise_num, trial_num))

    print(
        f"Starting batch: tutor={tutor_prompt} judge_prompt={judge_prompt} "
        f"judge_rubric={judge_rubric} personas={len(personas)} "
        f"course_exercises={len(selected_course_exercises)} runs={len(run_specs)} "
        f"turn_size={args.turn_size} trials={args.trials}"
    )

    success_count = 0
    fail_count = 0
    for idx, (persona_name, course, exercise_num, trial_num) in enumerate(run_specs, start=1):
        print(
            f"[{idx}/{len(run_specs)}] persona={persona_name} "
            f"course={course} exercise={exercise_num} trial={trial_num}"
        )
        try:
            assignment_text = _load_assignment_text(course, exercise_num, args.turn_size)
            system_prompt = load_system_prompt(tutor_prompt, assignment_override=assignment_text)
            tutor_graph = create_tutor_graph(system_prompt)
            student_graph = build_student_graph(prompt_name=persona_name)

            tutor_messages: list = []
            student_messages: list = [HumanMessage(content="Hi. What would you like to work on today?")]
            transcript_exchanges: list[dict[str, object]] = []

            for turn_idx in range(args.turn_size):
                student_msg = get_next_student_message(
                    student_messages,
                    assignment=assignment_text,
                    turn_size=args.turn_size,
                    graph=student_graph,
                )
                student_text = (
                    student_msg.content
                    if isinstance(student_msg.content, str)
                    else str(student_msg.content)
                )

                tutor_messages.append(HumanMessage(content=student_text))
                tutor_messages, tutor_text = get_tutor_reply(
                    tutor_messages,
                    graph=tutor_graph,
                )

                student_messages.append(student_msg)
                student_messages.append(HumanMessage(content=tutor_text))
                transcript_exchanges.append(
                    {"turn": turn_idx + 1, "student": student_text, "tutor": tutor_text}
                )

            persona_type = _persona_type_from_prompt_name(persona_name)
            persona_transcript_dir = _TRANSCRIPTS_DIR / persona_type
            persona_transcript_dir.mkdir(parents=True, exist_ok=True)
            transcript_num = _next_transcript_number(persona_transcript_dir)
            transcript_name = f"transcript_{transcript_num}"
            transcript_path = persona_transcript_dir / f"{transcript_name}.json"

            transcript_payload = {
                "tutor_prompt": tutor_prompt,
                "student_persona": persona_name,
                "course": course,
                "exercise_number": exercise_num,
                "turn_size": args.turn_size,
                "exercise": assignment_text,
                "judge_prompt": judge_prompt,
                "judge_rubric": judge_rubric,
                "trial": trial_num,
                "turns": len(transcript_exchanges),
                "exchanges": transcript_exchanges,
            }
            transcript_path.write_text(
                json.dumps(transcript_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            relative_stem = f"{persona_type}/{transcript_name}"
            result = judge_transcript(
                relative_stem,
                prompt_name=judge_prompt,
                rubric_name=judge_rubric,
            )
            print(f"  OK -> {relative_stem}.json score={result.total_score}/{result.max_score}")
            success_count += 1
        except (FileNotFoundError, RuntimeError, JudgeError, ValueError) as e:
            fail_count += 1
            print(f"  FAILED: {e}")

    print(f"Batch finished. success={success_count} failed={fail_count}")
    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

