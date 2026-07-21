"""Batch runner for RAG-context tutor simulations (SC2x exercises + practice).

Unlike ``internal_testing.run_transcript`` — which bakes the full course.txt + syllabus +
*entire* lecture transcripts into the tutor's system prompt — this runner drives
the tutor in **RAG mode**: the tutor's base prompt carries only the exercise, and
the relevant lecture chunks are retrieved per student turn (``rag.retrieve``) and
folded into the tutor's system message (after the cacheable prompt), mirroring the
deployed ``sandbox_ui`` behaviour (``services/tutor_bridge.py`` with ``context_mode="rag"``).

It also supports **practice problems** (``practices/practice_<NN>.txt``) as a
first-class problem kind alongside graded exercises.

Run matrix: ``problems x personas x trials`` for one course/tutor/provider.

Example (the default 162-conversation SC2x round: 3 exercises + 3 practice x 9
personas x 3 trials, Claude tutor, ~15 workers):

    python -m internal_testing.run_transcript_rag --yes

Smoke-test a single conversation first:

    python -m internal_testing.run_transcript_rag --limit 1 --yes

Output: ``transcripts/<type>/<type>_raw/transcript_NN.json`` (judge-compatible
schema, plus ``context_mode``/``exercise_kind`` metadata).
"""

from __future__ import annotations

import argparse
import json
import os
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

from internal_testing.run_transcript import _next_transcript_number  # noqa: E402
from internal_testing.stem_tutor_adapter import StemTutorAdapter  # noqa: E402
from rag.retrieve import format_context, has_index, retrieve_scored, to_records  # noqa: E402
from ui_core.tutor_bridge import RETRIEVED_CONTEXT_HEADER, RetrievedContext  # noqa: E402
from students.run_student import build_graph as build_student_graph  # noqa: E402
from students.run_student import get_next_student_message, list_personas  # noqa: E402
from tutor.run_tutor import (  # noqa: E402
    create_tutor_graph,
    load_system_prompt,
    parse_tutor_response,
)
from tutor.run_tutor import get_tutor_reply as upstream_get_tutor_reply  # noqa: E402
from utils.curriculum import (  # noqa: E402
    SOLUTION_CONTEXT_LABEL,
    append_course_tutor_rules,
    exercise_path,
    practice_path,
    read_course_description,
    read_pinned_context,
    read_solution,
)
from utils.figures import discover_figures, figure_filenames  # noqa: E402
from utils.pricing import model_from_message, priced, usage_from_message  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CURRICULUM_DIR = _REPO_ROOT / "curriculum"
_TRANSCRIPTS_DIR = _REPO_ROOT / "transcripts"

_TUTOR_GREETING = "Hi. What would you like to work on today?"
_TUTOR_CALL_MAX_RETRIES = 3
_SAVE_LOCK = threading.Lock()

DEFAULT_COURSE = "supply_chain_design"
DEFAULT_TUTOR = "tutor_07"
DEFAULT_PROVIDER = "claude"
DEFAULT_TURN_SIZE = 10
DEFAULT_TRIALS = 3
DEFAULT_WORKERS = 15
DEFAULT_OUTPUT_SUFFIX = "raw"
# Gen Z-voiced variants only: 01 (scripted), 02 (unscripted), 03 (strategy-sweep)
# — one per behavior mode, giving diversity without the formal-register duplicates.
DEFAULT_PERSONAS = [
    f"{ptype}_{i:02d}"
    for ptype in ("chaotic", "clueless", "cooperative")
    for i in (1, 2, 3)
]
# (kind, number) — 3 graded exercises + 3 practice problems.
DEFAULT_PROBLEMS = [
    ("exercise", "1"),
    ("exercise", "2"),
    ("exercise", "3"),
    ("practice", "1"),
    ("practice", "2"),
    ("practice", "3"),
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
    # "asktim" = our tutor (RAG context); "stem" = vendored MIT tutor (no context).
    tutor_impl: str = "asktim"

    @property
    def persona_type(self) -> str:
        """Family prefix of the persona (text before the first underscore)."""
        return self.persona.split("_", 1)[0]

    @property
    def context_mode(self) -> str:
        """Retrieval mode this arm runs under (the STEM tutor gets no lectures)."""
        return "rag" if self.tutor_impl == "asktim" else "none"


# --------------------------------------------------------------------------- #
# Context builders
# --------------------------------------------------------------------------- #

def _problem_text(course: str, kind: str, number: str) -> str:
    """Read the exercise or practice problem prompt text for the given course."""
    path = practice_path(course, number) if kind == "practice" else exercise_path(course, number)
    return path.read_text(encoding="utf-8").strip()


def _problem_label(kind: str) -> str:
    """Human-readable label for a problem kind ("Practice problem" or "Exercise")."""
    return "Practice problem" if kind == "practice" else "Exercise"


def _tutor_rag_assignment(course: str, kind: str, number: str, turn_size: int) -> str:
    """Tutor's RAG base prompt, mirroring the live bridges' ``rag`` mode.

    Pinned reference docs (``pinned/*.txt`` — course description, syllabus, guides)
    are baked in (they're pinned, not retrieved); lectures are reached via per-turn
    retrieval. Then the problem, its paired tutor-only solution, and the run config.
    """
    parts: list[str] = []
    pinned = read_pinned_context(course)
    if pinned:
        parts.append(pinned)
    parts.append(f"{_problem_label(kind)}:\n" + _problem_text(course, kind, number))
    # Tutor-only correct-answer reference, paired to the current problem (mirrors
    # the live bridges). Never given to the student model (_student_assignment_text).
    solution = read_solution(course, number, kind=kind)
    if solution.strip():
        parts.append(SOLUTION_CONTEXT_LABEL + solution.strip())
    parts.append(
        f"Run configuration:\n- Planned conversation length: {turn_size} student+tutor exchanges."
    )
    return "\n\n".join(parts)


def _student_assignment_text(config: RunConfig) -> str:
    """What the student model sees: the problem prompt only (no course / syllabus /
    lectures) plus the run configuration. The simulated student behaves like a
    learner who has just the assignment in front of them.
    """
    parts = [
        f"{_problem_label(config.kind)}:\n"
        + _problem_text(config.course, config.kind, config.number),
        f"Run configuration:\n- Planned conversation length: {config.turn_size} student+tutor exchanges.",
    ]
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- #
# Conversation loop
# --------------------------------------------------------------------------- #

def _retrieved_context(course: str, query: str, max_week: int | None = None) -> RetrievedContext:
    """Relevant chunks for this turn (prompt text + records); empty on any failure.

    *max_week* scopes retrieval to weeks the student has reached (drops later
    lectures/practices) so simulated transcripts match the live tutor's scope.
    """
    try:
        scored = retrieve_scored(course, query, max_week=max_week)
        return RetrievedContext(
            text=format_context([c for c, _ in scored], course), records=to_records(scored)
        )
    except Exception:
        return RetrievedContext()


def _tutor_reply_with_retry(tutor_messages: list, tutor_graph, rebuild, retrieved_context=""):
    """Call the tutor, retrying transient failures (rate limits, payload parse)
    with linear backoff. Rebuilds the graph between attempts in case client
    state is corrupted. *retrieved_context* is this turn's RAG grounding, folded
    into the system message by the tutor graph."""
    last_error: Exception | None = None
    for attempt in range(1, _TUTOR_CALL_MAX_RETRIES + 1):
        try:
            return upstream_get_tutor_reply(
                tutor_messages, graph=tutor_graph, retrieved_context=retrieved_context
            )
        except Exception as error:  # noqa: BLE001
            last_error = error
            if attempt < _TUTOR_CALL_MAX_RETRIES:
                time.sleep(2 * attempt)
                tutor_graph = rebuild()
                continue
    raise RuntimeError(f"Tutor call failed after {_TUTOR_CALL_MAX_RETRIES} attempts: {last_error}")


def _run_conversation(config: RunConfig) -> list[dict[str, object]]:
    """Simulate one full student/tutor conversation with per-turn RAG retrieval.

    Drives ``turn_size`` exchanges: for each turn the student model speaks, relevant
    course chunks are retrieved and prepended to the tutor input, and the tutor
    replies. Returns the list of exchange records (student/tutor text, pedagogical
    reasoning, retrieved chunks, and per-turn cost estimate).
    """
    tutor_assignment = _tutor_rag_assignment(
        config.course, config.kind, config.number, config.turn_size
    )
    system_prompt = load_system_prompt(config.tutor_prompt, assignment_override=tutor_assignment)
    # Append the course's per-course tutor rules (curriculum/<course>/tutor_rules.txt),
    # if any, so judged transcripts reflect the exact deployed prompt.
    system_prompt = append_course_tutor_rules(system_prompt, config.course)
    # Figures only apply to graded exercises (naming is exercise_<NN>_*); practice
    # problems have none, and reusing a matching number would wrongly attach them.
    figures = discover_figures(config.course, config.number) if config.kind == "exercise" else []
    # Scope retrieval to weeks the student has reached: the problem number is the
    # week number, so cap lecture/practice retrieval at it (drop later weeks).
    try:
        max_week = int(str(config.number).strip())
    except (TypeError, ValueError):
        max_week = None

    def _build_graph():
        """Construct a fresh tutor graph for this config's provider and figures."""
        return create_tutor_graph(system_prompt, provider=config.provider, figures=figures)

    # The STEM arm swaps in the vendored MIT tutor behind the same reply seam and
    # runs without retrieval (see meeting_notes/2026-07-21.md — round one is
    # deliberately no-context, matching how that tutor ships).
    is_stem = config.tutor_impl == "stem"
    stem_adapter = (
        StemTutorAdapter(
            course=config.course,
            kind=config.kind,
            number=config.number,
            problem_text=_problem_text(config.course, config.kind, config.number),
            turn_size=config.turn_size,
            provider=config.provider,
        )
        if is_stem
        else None
    )

    tutor_graph = None if is_stem else _build_graph()
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

        # RAG: retrieve relevant chunks for this student turn. They're folded into
        # the tutor's system message (matching the deployed ui_core.tutor_bridge),
        # not onto the student's turn — so the student's words stay clean and stale
        # RAG doesn't accumulate in the growing history. ``rc.records`` captures what
        # was retrieved (source/score/text) for the transcript.
        rc = RetrievedContext() if is_stem else _retrieved_context(config.course, student_text, max_week)
        rag_block = f"{RETRIEVED_CONTEXT_HEADER}\n\n{rc.text}" if rc.text else ""
        tutor_messages.append(HumanMessage(content=student_text))

        if is_stem:
            tutor_messages, tutor_text = stem_adapter.reply(tutor_messages)
            # The MIT tutor's analogue of pedagogical reasoning: the intents it
            # routed on plus the assessor's raw JSON (see StemTutorAdapter).
            tutor_reasoning = stem_adapter.last_reasoning
            last_msg = stem_adapter.last_reply_message
        else:
            tutor_messages, tutor_text = _tutor_reply_with_retry(
                tutor_messages, tutor_graph, _build_graph, retrieved_context=rag_block
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

        # Per-turn cost estimate: student (gpt) + tutor (provider) LLM calls, with
        # exact token counts from usage_metadata, plus the RAG query embedding
        # (tokens estimated from query length). $ conversion uses utils.pricing.
        student_model = model_from_message(
            student_message, os.environ.get("OPENAI_MODEL", "gpt-5.4")
        )
        tutor_fallback = (
            os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
            if config.provider == "claude"
            else os.environ.get("OPENAI_MODEL", "gpt-5.4")
        )
        tutor_model = model_from_message(last_msg, tutor_fallback)
        embed_model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
        emb_tokens = max(1, round(len(student_text) / 4))  # query-embedding estimate
        turn_calls = {
            "student": priced(student_model, usage_from_message(student_message)),
            "tutor": priced(tutor_model, usage_from_message(last_msg)),
        }
        if is_stem:
            # The MIT tutor spends a second, blocking model call per turn on its
            # assessment step. Counting only the reply would understate it ~2x and
            # make the cost comparison meaningless.
            turn_calls["tutor_assessment"] = priced(
                model_from_message(stem_adapter.last_assessment_message, tutor_fallback),
                usage_from_message(stem_adapter.last_assessment_message),
            )
        else:
            turn_calls["embedding"] = {
                **priced(embed_model, {"input_tokens": emb_tokens}),
                "tokens_estimated": True,
            }
        turn_usd = round(sum(c["usd"] for c in turn_calls.values()), 6)

        exchanges.append(
            {
                "turn": turn_index + 1,
                "student": student_text,
                "tutor": tutor_text,
                "pedagogical_reasoning": tutor_reasoning,
                # What RAG pulled for this turn: [{source, score, chars, text}].
                "retrieved": rc.records,
                # Estimated cost of producing this turn (see cost_estimate below).
                "cost": {"usd": turn_usd, "calls": turn_calls},
            }
        )

    return exchanges


def _aggregate_cost(exchanges: list[dict[str, object]]) -> dict:
    """Sum per-turn costs into a transcript-level estimate (total / component / model)."""
    total = 0.0
    by_component: dict[str, float] = {"student": 0.0, "tutor": 0.0, "embedding": 0.0}
    # "tutor_assessment" (STEM arm only) is added on demand by the loop below.
    by_model: dict[str, dict] = {}
    placeholder = False
    for e in exchanges:
        cost = e.get("cost") or {}
        total += cost.get("usd", 0.0)
        for comp, call in (cost.get("calls") or {}).items():
            by_component[comp] = by_component.get(comp, 0.0) + call.get("usd", 0.0)
            m = call.get("model", "?")
            bm = by_model.setdefault(
                m,
                {"input_tokens": 0, "output_tokens": 0, "cache_read": 0, "cache_write": 0, "usd": 0.0},
            )
            for k in ("input_tokens", "output_tokens", "cache_read", "cache_write"):
                bm[k] += int(call.get(k, 0) or 0)
            bm["usd"] += call.get("usd", 0.0)
            placeholder = placeholder or call.get("rate_is_placeholder", False)
    return {
        "total_usd": round(total, 6),
        "by_component_usd": {k: round(v, 6) for k, v in by_component.items()},
        "by_model": {m: {**v, "usd": round(v["usd"], 6)} for m, v in by_model.items()},
        "rates_note": (
            "LLM rates are PLACEHOLDERS — verify and override via PRICE_* env vars"
            if placeholder
            else "rates from utils.pricing"
        ),
    }


def _save_transcript(
    config: RunConfig, exchanges: list[dict[str, object]], output_suffix: str
) -> Path:
    """Write the conversation and its metadata to a numbered transcript JSON file.

    Assembles the judge-facing payload (lean course context, problem prompt, figures,
    aggregated cost) plus the exchanges, allocates the next transcript number under a
    lock, and returns the written path.
    """
    output_dir = _TRANSCRIPTS_DIR / config.persona_type / f"{config.persona_type}_{output_suffix}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Judge inputs (see the rubric): the judge grades tutor *behavior*, so it needs
    # only the conversation + the problem prompt + a short course description — never
    # the full lecture corpus (which the RAG tutor never saw anyway; what it actually
    # retrieved per turn is in each exchange's ``retrieved`` field). Keep the
    # transcript lean: context = the course description, exercise = the problem prompt.
    context_text = read_course_description(config.course)
    exercise_text = (
        f"{_problem_label(config.kind)}:\n"
        + _problem_text(config.course, config.kind, config.number)
        + "\n\nRun configuration:\n- Planned conversation length: "
        + f"{config.turn_size} student+tutor exchanges."
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
            # The STEM arm uses the vendored tutor's own prompts; recording our
            # --tutor value there would wrongly imply tutor_07 shaped its replies.
            "tutor_prompt": (
                config.tutor_prompt
                if config.tutor_impl == "asktim"
                else "open_learning_ai_tutor (vendored)"
            ),
            "student_persona": config.persona,
            "course": config.course,
            "exercise_number": config.number,
            "exercise_kind": config.kind,
            "tutor_impl": config.tutor_impl,
            "context_mode": config.context_mode,
            "figures": figure_names,
            "turn_size": config.turn_size,
            "context": context_text,
            "exercise": exercise_text,
            "turns": len(exchanges),
            "cost_estimate": _aggregate_cost(exchanges),
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
    """Expand the parsed args into one RunConfig per persona x problem x trial.

    Applies ``--limit`` (if set) to cap the returned configs for smoke tests.
    """
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
                        tutor_impl=args.tutor_impl,
                    )
                )
    if args.limit is not None:
        configs = configs[: args.limit]
    return configs


def _parse_problems(raw: list[str] | None) -> list[tuple[str, str]]:
    """Parse ``exercise:NN``/``practice:NN`` tokens into (kind, number) pairs.

    Returns DEFAULT_PROBLEMS when no tokens are given; raises ValueError on a
    malformed token.
    """
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
    """Parse command-line arguments for the RAG batch runner, resolving --problems."""
    p = argparse.ArgumentParser(description="RAG-context tutor/student batch simulations")
    p.add_argument("--course", default=DEFAULT_COURSE)
    p.add_argument("--tutor", default=DEFAULT_TUTOR)
    p.add_argument("--provider", choices=["gpt", "claude"], default=DEFAULT_PROVIDER)
    p.add_argument(
        "--tutor-impl",
        choices=["asktim", "stem"],
        default="asktim",
        help="Which tutor to drive: ours (RAG context) or the vendored MIT STEM tutor (no context).",
    )
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
    p.add_argument("--limit", type=int, default=None, help="Only run the first N configs (smoke test).")
    p.add_argument("--yes", "-y", action="store_true")
    args = p.parse_args()
    args.problems = _parse_problems(args.problems)
    return args


def main() -> int:
    """CLI entry point: validate personas/index, then run the batch in a thread pool.

    Returns 0 if every conversation succeeded, 1 otherwise (or on failed validation).
    """
    args = _parse_args()

    unknown = set(args.personas) - set(list_personas())
    if unknown:
        print(f"Unknown personas: {sorted(unknown)}")
        return 1
    # The STEM arm runs without retrieval, so a missing index isn't fatal for it.
    if args.tutor_impl == "asktim" and not has_index(args.course):
        print(f"No RAG index for course {args.course!r} — build it first (python -m rag.ingest ...).")
        return 1

    configs = _iter_configs(args)
    total = len(configs)
    print(
        f"RAG batch: {total} conversation(s) | course={args.course} tutor={args.tutor} "
        f"impl={args.tutor_impl} provider={args.provider} | "
        f"{len(args.personas)} personas x {len(args.problems)} problems "
        f"x {args.trials} trials | turns={args.turn_size} workers={args.workers} "
        f"-> *_{args.output_suffix}/"
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
        """Run and save one conversation, returning an ok/config/path or failure dict."""
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
