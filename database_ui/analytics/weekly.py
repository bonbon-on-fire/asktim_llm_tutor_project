# database_ui/analytics/weekly.py
"""CLI + orchestration for the weekly report cache.

Run: ``python -m database_ui.analytics.weekly [--week YYYY-MM-DD] [--max-convos N]``.
Judges every in-window conversation (reusing unchanged prior verdicts by
transcript hash), then writes the committed cache and a sibling report.md.
"""
from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timezone
from pathlib import Path

from database_ui.analytics import cache as cache_mod
from database_ui.analytics import data as data_mod
from database_ui.analytics.examples import pick_examples
from database_ui.analytics.flags import build_flags
from database_ui.analytics.judge import AnthropicJudge, Judge, Verdict, transcript_hash
from database_ui.analytics.report import render_report
from database_ui.analytics.stats import compute_stats, is_tutor, week_over_week
from database_ui.analytics.topics import aggregate_topics
from database_ui.analytics.weeks import Week, previous_complete_week, parse_week


def _first_question(transcript: list[tuple[str, str]]) -> str:
    for role, content in transcript:
        if not is_tutor(role):
            return content
    return ""


def run_week(
    db,
    week: Week,
    judge: Judge,
    *,
    judge_model: str,
    generated_at: datetime,
    prior_cache: dict | None = None,
    max_convos: int | None = None,
) -> tuple[Path, str]:
    courses = None  # the job always runs unscoped; the dashboard scopes on read
    convs = data_mod.fetch_conversations(db, week, courses)
    if max_convos is not None:
        convs = convs[:max_convos]
    conv_ids = [c.id for c in convs]
    msgs = data_mod.fetch_messages(db, conv_ids)
    returning = data_mod.prior_usernames(db, week.start_utc, courses)

    prior_verdicts = (prior_cache or {}).get("conversations", {})
    prior_hashes = (prior_cache or {}).get("_hashes", {})

    verdicts: dict[str, Verdict] = {}
    hashes: dict[str, str] = {}
    judged_dict: dict[str, dict] = {}
    first_q: dict[str, str] = {}
    skipped = 0
    for conv in convs:
        transcript = data_mod.fetch_transcript(db, conv.id)
        first_q[conv.id] = _first_question(transcript)
        h = transcript_hash(transcript)
        hashes[conv.id] = h
        if prior_hashes.get(conv.id) == h and conv.id in prior_verdicts:
            entry = prior_verdicts[conv.id]
            verdict = Verdict(
                worked_well=entry["worked_well"], issues=entry["issues"],
                topics=entry["topics"], one_line=entry["one_line"],
            )
        else:
            verdict = judge.judge(conv.course, transcript)
        verdicts[conv.id] = verdict
        judged_dict[conv.id] = verdict.as_dict(conv.course)

    flags = build_flags(convs, msgs, verdicts)
    topics = aggregate_topics(convs, verdicts, first_q)
    examples = pick_examples(convs, msgs, verdicts, seed=week.key)

    path = cache_mod.write_cache(
        week, judged_dict, examples, topics,
        judge_model=judge_model, generated_at=generated_at,
        judged_count=len(convs), skipped=skipped,
    )
    # Persist hashes alongside for next run's reuse (kept out of the scope-filtered read).
    blob = cache_mod.read_cache(week.key)
    blob["_hashes"] = hashes
    path.write_text(__import__("json").dumps(blob, indent=2, ensure_ascii=False), encoding="utf-8")

    stats = compute_stats(convs, msgs, returning)
    prior_week = week.prev()
    # Prior stats are recomputed live only if we still have the data; else empty deltas.
    prior_stats = _prior_stats(db, prior_week) if _has_data(db, prior_week) else {}
    wow = week_over_week(stats, prior_stats) if prior_stats else {}

    md = render_report(week, stats, wow, flags, topics,
                       judged_count=len(convs), judge_model=judge_model, skipped=skipped)
    (path.parent / "report.md").write_text(md, encoding="utf-8")
    return path, md


def _has_data(db, week: Week) -> bool:
    return bool(data_mod.fetch_conversations(db, week, None))


def _prior_stats(db, week: Week) -> dict:
    convs = data_mod.fetch_conversations(db, week, None)
    msgs = data_mod.fetch_messages(db, [c.id for c in convs])
    returning = data_mod.prior_usernames(db, week.start_utc, None)
    return compute_stats(convs, msgs, returning)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="database_ui.analytics.weekly")
    parser.add_argument("--week", default=None, help="YYYY-MM-DD in the target week")
    parser.add_argument("--max-convos", type=int, default=None)
    parser.add_argument("--report-out", default=None)
    args = parser.parse_args(argv)

    week = parse_week(args.week) if args.week else previous_complete_week(date.today())
    judge_model = os.environ.get("ANALYTICS_JUDGE_MODEL", "claude-sonnet-5")

    from database_ui.db.session import SessionLocal
    db = SessionLocal()
    try:
        prior = cache_mod.read_cache(week.key)   # reuse this week's own prior run if any
        judge = AnthropicJudge(judge_model)
        path, md = run_week(
            db, week, judge, judge_model=judge_model,
            generated_at=datetime.now(timezone.utc),
            prior_cache=prior, max_convos=args.max_convos,
        )
    finally:
        db.rollback()
        db.close()

    if args.report_out:
        Path(args.report_out).write_text(md, encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
