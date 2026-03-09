"""
Terminal UI — orchestrates a tutor-vs-student conversation run.

Pipeline (no ML in this file):
  0. Pick tutor prompt version
  1. Pick student persona type (chaotic / chitchat / clueless)
  2. Pick student persona version
  3. Pick course
  4. Pick exercise
  5. Pick number of turns
  6. Run conversation and display it
  7. Pick judge prompt version
  8. Pick judge rubric version
  9. Auto-save transcript and run judge
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from langchain_core.messages import HumanMessage

from judge import JudgeError, judge_transcript
from students.run_student import build_graph as build_student_graph
from students.run_student import get_next_student_message
from tutor.run_tutor import get_tutor_reply, create_tutor_graph, load_system_prompt

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TUTOR_PROMPTS_DIR = _REPO_ROOT / "tutor" / "prompts"
_PERSONAS_DIR = _REPO_ROOT / "students" / "personas"
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_JUDGE_PROMPTS_DIR = _REPO_ROOT / "judge" / "prompts"
_JUDGE_RUBRICS_DIR = _REPO_ROOT / "judge" / "rubrics"
_TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"

_PERSONA_TYPES: tuple[str, ...] = ("chaotic", "chitchat", "clueless")

# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def _discover_tutor_versions() -> list[str]:
    """Return sorted tutor prompt stems (e.g. ['tutor_01'])."""
    if not _TUTOR_PROMPTS_DIR.exists():
        return []
    return sorted(p.stem for p in _TUTOR_PROMPTS_DIR.glob("*.txt"))


def _discover_persona_versions(persona_type: str) -> list[str]:
    """Return sorted version numbers for a persona type (e.g. ['01', '02'])."""
    versions: list[str] = []
    for p in sorted(_PERSONAS_DIR.glob(f"{persona_type}_*.txt")):
        m = re.match(rf"^{re.escape(persona_type)}_(\d{{2}})\.txt$", p.name)
        if m:
            versions.append(m.group(1))
    return versions


def _discover_courses() -> list[str]:
    """Return sorted course folder names under curriculum/."""
    if not _CURRICULUM_DIR.exists():
        return []
    return sorted(d.name for d in _CURRICULUM_DIR.iterdir() if d.is_dir())


def _discover_exercises(course: str) -> list[str]:
    """Return sorted exercise numbers for a course (e.g. ['01', '02', '03'])."""
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
    """Load combined assignment context with turn-size metadata."""
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


def _discover_judge_versions() -> list[str]:
    """Return sorted judge prompt stems (e.g. ['judge_01'])."""
    if not _JUDGE_PROMPTS_DIR.exists():
        return []
    return sorted(p.stem for p in _JUDGE_PROMPTS_DIR.glob("*.txt"))


def _discover_judge_rubrics() -> list[str]:
    """Return sorted judge rubric stems (e.g. ['rubric_01'])."""
    if not _JUDGE_RUBRICS_DIR.exists():
        return []
    return sorted(p.stem for p in _JUDGE_RUBRICS_DIR.glob("*.md"))


def _next_transcript_number(persona_dir: Path) -> str:
    """Find the next available transcript_XX number in a persona subfolder."""
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


# ---------------------------------------------------------------------------
# Interactive prompts
# ---------------------------------------------------------------------------

def _prompt(msg: str) -> str:
    return input(msg).strip()


def _prompt_choice(label: str, options: list[str]) -> str:
    if not options:
        raise RuntimeError(f"No options available for: {label}")
    if len(options) == 1:
        print(f"{label}: {options[0]} (only option)")
        return options[0]
    display = ", ".join(options)
    while True:
        raw = _prompt(f"{label} ({display}): ")
        if raw in options:
            return raw
        print(f"  Please enter one of: {display}")


def _prompt_number(label: str, options: list[str]) -> str:
    """Prompt for a number from a list of zero-padded strings like ['01', '02']."""
    if not options:
        raise RuntimeError(f"No options available for: {label}")
    if len(options) == 1:
        print(f"{label}: {options[0]} (only option)")
        return options[0]
    display = f"{options[0]}..{options[-1]}"
    while True:
        raw = _prompt(f"{label} ({display}): ").strip().lstrip("0") or "0"
        padded = f"{int(raw):02d}" if raw.isdigit() else ""
        if padded in options:
            return padded
        print(f"  Please enter a number between {options[0]} and {options[-1]}")


def _prompt_turns() -> int:
    while True:
        raw = _prompt("Number of turns (student+tutor exchanges): ")
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
        print("  Please enter a positive integer.")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def main() -> int:
    # --- env check ---
    if not (os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_KEY")):
        print("OPENAI_API_KEY (or OPENAI_KEY) environment variable is required but not set.")
        return 1

    try:
        # 0. Tutor version
        tutor_versions = _discover_tutor_versions()
        tutor_version = _prompt_choice("Tutor prompt", tutor_versions)

        # 1. Student persona type
        persona_type = _prompt_choice("Student persona type", list(_PERSONA_TYPES))

        # 2. Student persona version
        persona_versions = _discover_persona_versions(persona_type)
        persona_version = _prompt_number(f"  {persona_type} version", persona_versions)
        prompt_name = f"{persona_type}_{persona_version}"

        # 3. Course
        courses = _discover_courses()
        course = _prompt_choice("Course", courses)

        # 4. Exercise
        exercise_numbers = _discover_exercises(course)
        exercise_num = _prompt_number(f"  Exercise in {course}", exercise_numbers)

        # 5. Turns
        turns = _prompt_turns()

    except (KeyboardInterrupt, EOFError):
        print("\nCancelled.")
        return 130

    # --- load assignment text (course context + exercise) ---
    try:
        assignment_text = _load_assignment_text(course, exercise_num, turns)
    except FileNotFoundError as e:
        print(f"Missing curriculum file: {e.filename}")
        return 1

    # --- build graphs ---
    system_prompt = load_system_prompt(tutor_version, assignment_override=assignment_text)
    tutor_graph = create_tutor_graph(system_prompt)
    student_graph = build_student_graph(prompt_name=prompt_name)

    # --- config summary ---
    print()
    print(f"[Config] tutor={tutor_version}  persona={prompt_name}  "
          f"course={course}  exercise={exercise_num}  turns={turns}")
    print()

    # 6. Run conversation
    tutor_greeting = "Hi. What would you like to work on today?"
    print("[Tutor]", tutor_greeting, "\n")

    transcript_exchanges: list[dict[str, object]] = []
    tutor_messages: list = []
    student_messages: list = [HumanMessage(content=tutor_greeting)]

    try:
        for turn_idx in range(turns):
            student_msg = get_next_student_message(
                student_messages,
                assignment=assignment_text,
                turn_size=turns,
                graph=student_graph,
            )
            student_text = student_msg.content if isinstance(student_msg.content, str) else str(student_msg.content)
            print(f"[Student] {student_text}\n")

            tutor_messages.append(HumanMessage(content=student_text))
            tutor_messages, tutor_text = get_tutor_reply(
                tutor_messages,
                graph=tutor_graph,
            )
            print(f"[Tutor] {tutor_text}\n")

            student_messages.append(student_msg)
            student_messages.append(HumanMessage(content=tutor_text))

            transcript_exchanges.append({
                "turn": turn_idx + 1,
                "student": student_text,
                "tutor": tutor_text,
            })
    except KeyboardInterrupt:
        print("\nConversation interrupted.")
        if not transcript_exchanges:
            print("No turns completed. Exiting without saving.")
            return 130

    # 7. Judge prompt version
    try:
        judge_versions = _discover_judge_versions()
        judge_version = _prompt_choice("Judge prompt", judge_versions)
        judge_rubrics = _discover_judge_rubrics()
        judge_rubric = _prompt_choice("Judge rubric", judge_rubrics)
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. Exiting without saving.")
        return 130

    # 8. Auto-save transcript
    persona_transcript_dir = _TRANSCRIPTS_DIR / persona_type
    persona_transcript_dir.mkdir(parents=True, exist_ok=True)
    transcript_num = _next_transcript_number(persona_transcript_dir)
    transcript_name = f"transcript_{transcript_num}"
    transcript_path = persona_transcript_dir / f"{transcript_name}.json"

    transcript_payload = {
        "tutor_prompt": tutor_version,
        "student_persona": prompt_name,
        "course": course,
        "exercise_number": exercise_num,
        "turn_size": turns,
        "exercise": assignment_text,
        "judge_prompt": judge_version,
        "judge_rubric": judge_rubric,
        "turns": len(transcript_exchanges),
        "exchanges": transcript_exchanges,
    }
    transcript_path.write_text(
        json.dumps(transcript_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\nSaved transcript to: {transcript_path.relative_to(_REPO_ROOT)}")

    # Run judge
    relative_stem = f"{persona_type}/{transcript_name}"
    try:
        result = judge_transcript(relative_stem, prompt_name=judge_version, rubric_name=judge_rubric)
    except JudgeError as e:
        print(f"Judge failed: {e}")
        return 1
    print(f"[Judge] total_score={result.total_score}/{result.max_score}")
    return 0
