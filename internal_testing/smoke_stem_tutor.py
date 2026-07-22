"""Single-conversation smoke test for the STEM AskTIM adapter.

Runs one simulated student against MIT's tutor on a `supply_chain_design`
problem and prints each turn plus the assessor's raw JSON, so we can tell real
engagement from silent fallback before spending a batch on it.

    python -m internal_testing.smoke_stem_tutor
    python -m internal_testing.smoke_stem_tutor --persona clueless_01 --turns 3
    python -m internal_testing.smoke_stem_tutor --course physics_iii_vibrations_and_waves --number 1

Prints a verdict at the end: if every turn parsed to the same fallback code, the
assessor never really engaged and the run is measuring nothing.
"""

from __future__ import annotations

import argparse
import sys

# Tutor replies routinely contain arrows/dashes/math glyphs; the Windows console
# defaults to cp1252 and raises on the first one.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

from langchain_core.messages import HumanMessage  # noqa: E402

from internal_testing.run_transcript_rag import (  # noqa: E402
    _TUTOR_GREETING,
    _problem_text,
    _student_assignment_text,
    RunConfig,
)
from internal_testing.stem_tutor_adapter import StemTutorAdapter  # noqa: E402
from students.run_student import build_graph as build_student_graph  # noqa: E402
from students.run_student import get_next_student_message  # noqa: E402

_RULE = "=" * 78


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smoke-test the STEM AskTIM adapter")
    p.add_argument("--course", default="supply_chain_design")
    p.add_argument("--kind", choices=["exercise", "practice"], default="exercise")
    p.add_argument("--number", default="1")
    p.add_argument("--persona", default="cooperative_01")
    p.add_argument("--provider", choices=["gpt", "claude"], default="claude")
    p.add_argument("--turns", type=int, default=3)
    p.add_argument(
        "--no-solution",
        action="store_true",
        help="Withhold the tutor-only solution (expect the assessor to degrade).",
    )
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    problem_text = _problem_text(args.course, args.kind, args.number)
    adapter = StemTutorAdapter(
        course=args.course,
        kind=args.kind,
        number=args.number,
        problem_text=problem_text,
        turn_size=args.turns,
        provider=args.provider,
        include_solution=not args.no_solution,
    )
    if adapter.langsmith_was_set:
        print("[warn] LANGSMITH_API_KEY was set; unset for this run so prompts come "
              "from the vendored templates rather than LangSmith.")

    print(_RULE)
    print(f"STEM AskTIM smoke test | course={args.course} {args.kind}_{args.number} "
          f"persona={args.persona} provider={args.provider} turns={args.turns}")
    print(_RULE)

    config = RunConfig(
        course=args.course,
        tutor_prompt="n/a",
        provider=args.provider,
        persona=args.persona,
        kind=args.kind,
        number=args.number,
        turn_size=args.turns,
        trial=1,
    )
    student_graph = build_student_graph(prompt_name=args.persona)
    student_assignment = _student_assignment_text(config)

    student_messages = [HumanMessage(content=_TUTOR_GREETING)]
    tutor_messages: list = []
    selections: list[str] = []

    for turn in range(1, args.turns + 1):
        student_message = get_next_student_message(
            student_messages,
            assignment=student_assignment,
            turn_size=args.turns,
            graph=student_graph,
        )
        student_text = (
            student_message.content
            if isinstance(student_message.content, str)
            else str(student_message.content)
        )

        tutor_messages.append(HumanMessage(content=student_text))
        tutor_messages, tutor_text = adapter.reply(tutor_messages)

        student_messages.append(student_message)
        student_messages.append(HumanMessage(content=tutor_text))

        selections.append(adapter.last_assessment_raw)

        print(f"\n--- Turn {turn} " + "-" * 62)
        print(f"\n[STUDENT]\n{student_text}")
        print(f"\n[TUTOR]\n{tutor_text}")
        print(f"\n[INTENTS] {', '.join(adapter.last_intents) or '(none)'}")
        print(f"[ASSESSMENT] {adapter.last_assessment_raw or '(empty)'}")

    print("\n" + _RULE)
    distinct = {s.strip() for s in selections if s.strip()}
    if not distinct:
        print("VERDICT: assessor produced nothing — adapter is not wired correctly.")
        return 1
    if len(distinct) == 1 and args.turns > 1:
        print("VERDICT: assessor returned an identical response every turn. Could be "
              "genuine, but check it isn't the silent fallback before running a batch.")
    else:
        print(f"VERDICT: assessor varied across turns ({len(distinct)} distinct) — "
              "it is engaging with the problem.")
    print(_RULE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
