"""Batch runner for RAG-context tutor simulations (SC2x exercises + practice).

Unlike ``internal_ui.run_ui_raw`` — which bakes the full course.txt + syllabus +
*entire* lecture transcripts into the tutor's system prompt — this runner drives
the tutor in **RAG mode**: the tutor's base prompt carries only the exercise, and
the relevant lecture chunks are retrieved per student turn (``rag.retrieve``) and
prepended to that turn, mirroring the deployed ``sandbox_ui`` behaviour
(``services/tutor_bridge.py`` with ``context_mode="rag"``).

It also supports **practice problems** (``practices/practice_<NN>.txt``) as a
first-class problem kind alongside graded exercises.

Run matrix: ``problems x personas x trials`` for one course/tutor/provider.

Example (the 324-conversation SC2x round: 3 exercises + 3 practice x 18 personas
x 3 trials, Claude tutor, ~15 workers):

    python -m internal_ui.run_ui_raw_rag --yes

Smoke-test a single conversation first:

    python -m internal_ui.run_ui_raw_rag --limit 1 --yes

Output: ``transcripts/<type>/<type>_raw_rag/transcript_NN.json`` (judge-compatible
schema, plus ``context_mode``/``exercise_kind``/``student_context`` metadata).
"""

from __future__ import annotations

import argparse
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

# The internal runners don't auto-load .env; do it here so OPENAI_API_KEY /
# ANTHROPIC_API_KEY (tutor, student, and RAG embeddings) are available.
from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

from internal_ui.run_ui_raw import _next_transcript_number  # noqa: E402
from rag.retrieve import format_context, has_index  # noqa: E402
from rag.retrieve import retrieve as rag_retrieve  # noqa: E402
from students.run_student import build_graph as build_student_graph  # noqa: E402
from students.run_student import get_next_student_message, list_personas  # noqa: E402
from tutor.run_tutor import (  # noqa: E402
    create_tutor_graph,
    load_system_prompt,
    parse_tutor_response,
)
from tutor.run_tutor import get_tutor_reply as upstream_get_tutor_reply  # noqa: E402
from utils.curriculum import exercise_path, practice_path  # noqa: E402
from utils.figures import discover_figures, figure_filenames  # noqa: E402
from utils.lectures import load_lecture_transcripts  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"

_TUTOR_GREETING = "Hi. What would you like to work on today?"
_TUTOR_CALL_MAX_RETRIES = 3
_SAVE_LOCK = threading.Lock()

DEFAULT_COURSE = "supply_chain_design"
DEFAULT_TUTOR = "tutor_05"
DEFAULT_PROVIDER = "claude"
DEFAULT_TURN_SIZE = 10
DEFAULT_TRIALS = 3
DEFAULT_WORKERS = 15
DEFAULT_OUTPUT_SUFFIX = "raw_rag"
DEFAULT_PERSONAS = [
    f"{ptype}_{i:02d}"
    for ptype in ("chaotic", "clueless", "cooperative")
    for i in range(1, 7)
]
# (kind, number) — 3 graded exercises + 3 practice problems.
DEFAULT_PROBLEMS = [
    ("exercise", "01"),
    ("exercise", "02"),
    ("exercise", "03"),
    ("practice", "01"),
    ("practice", "02"),
    ("practice", "03"),
]


@dataclass(frozen=True)
class RunConfig:
    course: str
    tutor_prompt: str
    provider: str
    persona: str
    kind: str  # "exercise" | "practice"
    number: str
    turn_size: int
    trial: int
    student_context: str  # "full" | "no_lectures"

    @property
    def persona_type(self) -> str:
        return self.persona.split("_", 1)[0]


# --------------------------------------------------------------------------- #
# Context builders
# --------------------------------------------------------------------------- #

def _problem_text(course: str, kind: str, number: str) -> str:
    path = practice_path(course, number) if kind == "practice" else exercise_path(course, number)
    return path.read_text(encoding="utf-8").strip()


def _problem_label(kind: str) -> str:
    return "Practice problem" if kind == "practice" else "Exercise"


def _course_and_syllabus(course: str) -> list[str]:
    parts: list[str] = []
    course_dir = _CURRICULUM_DIR / course
    course_path = course_dir / "course.txt"
    if course_path.exists():
        parts.append("Course context:\n" + course_path.read_text(encoding="utf-8").strip())
    syllabus_path = course_dir / "syllabus.txt"
    if syllabus_path.exists():
        parts.append("Syllabus:\n" + syllabus_path.read_text(encoding="utf-8").strip())
    return parts


def _full_assignment_text(course: str, kind: str, number: str, turn_size: int) -> str:
    """Full context (course + syllabus + lectures + problem) — used for the
    saved transcript's ``exercise`` field so the judge sees the complete problem."""
    parts = _course_and_syllabus(course)
    lectures = load_lecture_transcripts(course)
    if lectures:
        parts.append("Lecture transcripts:\n" + lectures)
    parts.append(f"{_problem_label(kind)}:\n" + _problem_text(course, kind, number))
    parts.append(
        f"Run configuration:\n- Planned conversation length: {turn_size} student+tutor exchanges."
    )
    return "\n\n".join(parts)


def _tutor_rag_assignment(course: str, kind: str, number: str, turn_size: int) -> str:
    """Tutor's RAG base prompt: the problem only. Course/syllabus/lectures are
    reached via per-turn retrieval, not baked in."""
    parts = [
        f"{_problem_label(kind)}:\n" + _problem_text(course, kind, number),
        f"Run configuration:\n- Planned conversation length: {turn_size} student+tutor exchanges.",
    ]
    return "\n\n".join(parts)


def _student_assignment_text(config: RunConfig) -> str:
    """What the student model sees. ``no_lectures`` (default) keeps the student
    fast/cheap (course + syllabus + problem); ``full`` also folds in lectures to
    match the prior full-context round exactly."""
    parts = _course_and_syllabus(config.course)
    if config.student_context == "full":
        lectures = load_lecture_transcripts(config.course)
        if lectures:
            parts.append("Lecture transcripts:\n" + lectures)
    parts.append(
        f"{_problem_label(config.kind)}:\n" + _problem_text(config.course, config.kind, config.number)
    )
    parts.append(
        f"Run configuration:\n- Planned conversation length: {config.turn_size} student+tutor exchanges."
    )
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# Conversation loop
# --------------------------------------------------------------------------- #

def _retrieved_context(course: str, query: str) -> str:
    """Relevant lecture chunks for this turn; degrade to empty on any failure."""
    try:
        return format_context(rag_retrieve(course, query))
    except Exception:
        return ""


def _tutor_reply_with_retry(tutor_messages: list, tutor_graph, rebuild):
    """Call the tutor, retrying transient failures (rate limits, payload parse)
    with linear backoff. Rebuilds the graph between attempts in case client
    state is corrupted."""
    last_error: Exception | None = None
    for attempt in range(1, _TUTOR_CALL_MAX_RETRIES + 1):
        try:
            return upstream_get_tutor_reply(tutor_messages, graph=tutor_graph)
        except Exception as error:  # noqa: BLE001
            last_error = error
            if attempt < _TUTOR_CALL_MAX_RETRIES:
                time.sleep(2 * attempt)
                tutor_graph = rebuild()
                continue
    raise RuntimeError(f"Tutor call failed after {_TUTOR_CALL_MAX_RETRIES} attempts: {last_error}")


def _run_conversation(config: RunConfig) -> list[dict[str, object]]:
    tutor_assignment = _tutor_rag_assignment(
        config.course, config.kind, config.number, config.turn_size
    )
    system_prompt = load_system_prompt(config.tutor_prompt, assignment_override=tutor_assignment)
    # Figures only apply to graded exercises (naming is exercise_<NN>_*); practice
    # problems have none, and reusing a matching number would wrongly attach them.
    figures = discover_figures(config.course, config.number) if config.kind == "exercise" else []

    def _build_graph():
        return create_tutor_graph(system_prompt, provider=config.provider, figures=figures)

    tutor_graph = _build_graph()
    student_graph = build_student_graph(prompt_name=config.persona)
    student_assignment = _student_assignment_text(config)

    exchanges: list[dict[str, object]] = []
    tutor_messages: list = []
    student_messages: list = [HumanMessage(content=_TUTOR_GREETING)]

    for turn_index in range(config.turn_size):
        student_message = get_next_student_message(
            student_messages,
            assignment=student_assignment,
            turn_size=config.turn_size,
            figures=figures,
            graph=student_graph,
        )
        student_text = (
            student_message.content
            if isinstance(student_message.content, str)
            else str(student_message.content)
        )

        # RAG: retrieve relevant lecture chunks for this student turn and prepend
        # them as a reference block ahead of the student's actual message.
        retrieved = _retrieved_context(config.course, student_text)
        tutor_input = (
            f"{retrieved}\n\n---\n\nStudent message:\n{student_text}"
            if retrieved
            else student_text
        )
        tutor_messages.append(HumanMessage(content=tutor_input))
        tutor_messages, tutor_text = _tutor_reply_with_retry(
            tutor_messages, tutor_graph, _build_graph
        )

        tutor_reasoning = ""
        last_msg = tutor_messages[-1] if tutor_messages else None
        if isinstance(last_msg, AIMessage):
            raw = last_msg.content if isinstance(last_msg.content, str) else str(last_msg.content)
            parsed_reasoning, _ = parse_tutor_response(raw)
            if isinstance(parsed_reasoning, str) and parsed_reasoning.strip():
                tutor_reasoning = parsed_reasoning.strip()

        student_messages.append(student_message)
        student_messages.append(HumanMessage(content=tutor_text))
        exchanges.append(
            {
                "turn": turn_index + 1,
                "student": student_text,
                "tutor": tutor_text,
                "pedagogical_reasoning": tutor_reasoning,
            }
        )

    return exchanges


def _save_transcript(
    config: RunConfig, exchanges: list[dict[str, object]], output_suffix: str
) -> Path:
    output_dir = _TRANSCRIPTS_DIR / config.persona_type / f"{config.persona_type}_{output_suffix}"
    output_dir.mkdir(parents=True, exist_ok=True)

    full_assignment = _full_assignment_text(
        config.course, config.kind, config.number, config.turn_size
    )
    context_text = "\n\n".join(
        _course_and_syllabus(config.course)
        + (
            ["Lecture transcripts:\n" + load_lecture_transcripts(config.course)]
            if load_lecture_transcripts(config.course)
            else []
        )
    )
    figure_names = (
        figure_filenames(discover_figures(config.course, config.number))
        if config.kind == "exercise"
        else []
    )

    with _SAVE_LOCK:
        transcript_num = _next_transcript_number(output_dir)
        transcript_path = output_dir / f"transcript_{transcript_num}.json"
        payload = {
            "tutor_provider": config.provider,
            "tutor_prompt": config.tutor_prompt,
            "student_persona": config.persona,
            "course": config.course,
            "exercise_number": config.number,
            "exercise_kind": config.kind,
            "context_mode": "rag",
            "student_context": config.student_context,
            "figures": figure_names,
            "turn_size": config.turn_size,
            "context": context_text,
            "exercise": full_assignment,
            "turns": len(exchanges),
            "exchanges": exchanges,
        }
        transcript_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    return transcript_path


# --------------------------------------------------------------------------- #
# Bundle
# --------------------------------------------------------------------------- #

def _iter_configs(args) -> list[RunConfig]:
    configs: list[RunConfig] = []
    for persona in args.personas:
        for kind, number in args.problems:
            for trial in range(1, args.trials + 1):
                configs.append(
                    RunConfig(
                        course=args.course,
                        tutor_prompt=args.tutor,
                        provider=args.provider,
                        persona=persona,
                        kind=kind,
                        number=number,
                        turn_size=args.turn_size,
                        trial=trial,
                        student_context=args.student_context,
                    )
                )
    if args.limit is not None:
        configs = configs[: args.limit]
    return configs


def _parse_problems(raw: list[str] | None) -> list[tuple[str, str]]:
    if not raw:
        return DEFAULT_PROBLEMS
    out: list[tuple[str, str]] = []
    for token in raw:
        kind, _, number = token.partition(":")
        if kind not in ("exercise", "practice") or not number:
            raise ValueError(f"Bad --problems token {token!r}; expected exercise:NN or practice:NN")
        out.append((kind, number))
    return out


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="RAG-context tutor/student batch simulations")
    p.add_argument("--course", default=DEFAULT_COURSE)
    p.add_argument("--tutor", default=DEFAULT_TUTOR)
    p.add_argument("--provider", choices=["gpt", "claude"], default=DEFAULT_PROVIDER)
    p.add_argument("--personas", nargs="+", default=DEFAULT_PERSONAS)
    p.add_argument(
        "--problems",
        nargs="+",
        default=None,
        help="Tokens like exercise:01 practice:02 (default: 3 exercises + 3 practice)",
    )
    p.add_argument("--turn-size", type=int, default=DEFAULT_TURN_SIZE)
    p.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    p.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    p.add_argument("--output-suffix", default=DEFAULT_OUTPUT_SUFFIX)
    p.add_argument(
        "--student-context",
        choices=["full", "no_lectures"],
        default="no_lectures",
        help="What the student model sees (default: no_lectures — faster/cheaper; "
        "full also folds lectures in to match the prior full-context round).",
    )
    p.add_argument("--limit", type=int, default=None, help="Only run the first N configs (smoke test).")
    p.add_argument("--yes", "-y", action="store_true")
    args = p.parse_args()
    args.problems = _parse_problems(args.problems)
    return args


def main() -> int:
    args = _parse_args()

    unknown = set(args.personas) - set(list_personas())
    if unknown:
        print(f"Unknown personas: {sorted(unknown)}")
        return 1
    if not has_index(args.course):
        print(f"No RAG index for course {args.course!r} — build it first (python -m rag.ingest ...).")
        return 1

    configs = _iter_configs(args)
    total = len(configs)
    print(
        f"RAG batch: {total} conversation(s) | course={args.course} tutor={args.tutor} "
        f"provider={args.provider} | {len(args.personas)} personas x {len(args.problems)} problems "
        f"x {args.trials} trials | turns={args.turn_size} workers={args.workers} "
        f"student_context={args.student_context} -> *_{args.output_suffix}/"
    )
    if not args.yes:
        resp = input("Proceed? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print("Cancelled.")
            return 0

    failed = 0
    completed = 0
    start = time.monotonic()

    def _run_one(config: RunConfig) -> dict:
        try:
            exchanges = _run_conversation(config)
            path = _save_transcript(config, exchanges, args.output_suffix)
            return {"ok": True, "config": config, "path": path}
        except Exception as error:  # noqa: BLE001
            return {"ok": False, "config": config, "reason": str(error)}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(_run_one, c): c for c in configs}
        for future in as_completed(futures):
            completed += 1
            result = future.result()
            c = result["config"]
            tag = (
                f"[{completed}/{total}] {c.persona} {c.kind}_{c.number} trial={c.trial}"
            )
            if result["ok"]:
                rel = Path(result["path"]).relative_to(_REPO_ROOT)
                print(f"[OK] {tag} -> {rel}")
            else:
                failed += 1
                print(f"[FAIL] {tag} :: {result['reason']}")

    elapsed = time.monotonic() - start
    print(
        f"Done: {total - failed}/{total} succeeded, {failed} failed, in {elapsed/60:.1f} min."
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
