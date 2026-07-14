"""Generate a RAG retrieval ground-truth dataset for a course.

Builds a labeled set where each *student-voiced question* is pinned to the
specific lecture passage that answers it. Pinning is stored in **source
coordinates** — ``(lecture file, char span) + verbatim quote`` — not chunk ids,
so the labels stay valid across re-chunking and are comparable between different
RAG systems (the companion harness resolves a span to whichever chunks the
loaded index has).

Pipeline (passage -> question, so the gold is automatic):
  1. Segment each lecture's raw text into sentence-aligned passages with exact
     char offsets.
  2. For a spread of passages, ask Claude for a few questions a real student
     would ask that are answered by that passage, each with a verbatim quote.
  3. Locate the quote's char span in the source (drop/flag if not verbatim).
  4. Record retrieval signals against the current index (was the gold quote in
     the top-k? at what rank?) so hard cases can be kept and the baseline seen.

Output is JSONL, one row per question, written to
``eval/rag_judge/ground_truth/<course>.jsonl``. Rows carry ``flags`` for human review;
nothing is silently dropped except questions whose quote can't be located.

Usage:
    python eval/rag_judge/generate_ground_truth.py --course supply_chain_design \
        --num-passages 25 --questions-per-passage 2
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

load_dotenv(_REPO_ROOT / ".env")

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage, SystemMessage

from eval.rag_judge.render_markdown import render_file
from rag.retrieve import retrieve_scored

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+")
_WS = re.compile(r"\s+")

_SYSTEM = """You write evaluation questions for a supply-chain course's retrieval system.

Given ONE passage from a course lecture, produce questions a REAL student would \
ask a tutor that are answered by THIS passage specifically.

Rules:
- Each question must be answerable primarily from this passage, not generic.
- Write in a real student's voice: casual, short, first person (how do I…, why does…, \
what's the deal with…). Light shorthand is fine.
- For each question, copy a VERBATIM quote from the passage (word-for-word, no \
paraphrase) that contains the answer. Keep the quote to 1-2 sentences.
- Do not invent facts not in the passage.

Return ONLY a JSON array, no prose, no code fences:
[{"question": "...", "quote": "verbatim text copied from the passage"}]"""


def _segment(text: str, target: int, min_len: int) -> list[tuple[int, int, str]]:
    """Split *text* into sentence-aligned passages of roughly *target* chars.

    Returns ``(start, end, slice_text)`` with exact offsets into *text*; a
    trailing remainder shorter than *min_len* is dropped rather than kept as a
    stub passage.
    """
    boundaries = [m.end() for m in _SENTENCE_BOUNDARY.finditer(text)] + [len(text)]
    passages: list[tuple[int, int, str]] = []
    seg_start = 0
    for cut in boundaries:
        if cut - seg_start >= target:
            passages.append((seg_start, cut, text[seg_start:cut]))
            seg_start = cut
    if len(text) - seg_start >= min_len:
        passages.append((seg_start, len(text), text[seg_start:]))
    return passages


def _locate(haystack: str, needle: str) -> tuple[int, int] | None:
    """Find *needle* in *haystack*, tolerating whitespace differences.

    Returns the ``(start, end)`` char span or ``None`` if the quote isn't a
    verbatim (whitespace-flexible) match — i.e. the model paraphrased.
    """
    idx = haystack.find(needle)
    if idx >= 0:
        return idx, idx + len(needle)
    tokens = [re.escape(t) for t in needle.split()]
    if not tokens:
        return None
    match = re.compile(r"\s+".join(tokens)).search(haystack)
    return (match.start(), match.end()) if match else None


def _norm(text: str) -> str:
    """Whitespace-normalized, lowercased text for containment checks."""
    return _WS.sub(" ", text).strip().lower()


def _parse_json_array(raw: str) -> list[dict]:
    """Parse the model's reply into a list of dicts, tolerating stray fences/prose."""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1:
        return []
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict)]


def _retrieval_signal(course: str, question: str, quote: str) -> dict:
    """Retrieve for *question* over the current index; report if the gold was found.

    ``gold_rank`` is the 1-based position of the first retrieved chunk whose text
    contains the gold quote, or ``None`` on a miss (a hard/interesting case).
    """
    scored = retrieve_scored(course, question)
    norm_quote = _norm(quote)
    rank = None
    for i, (chunk, _score) in enumerate(scored):
        if norm_quote and norm_quote in _norm(chunk.text):
            rank = i + 1
            break
    return {
        "gold_hit": rank is not None,
        "gold_rank": rank,
        "retrieved_k": len(scored),
        "top_source": scored[0][0].source if scored else None,
    }


def _lecture_files(course: str, min_chars: int) -> list[Path]:
    """Lecture .txt files for *course* with at least *min_chars* of text, sorted."""
    lectures_dir = _REPO_ROOT / "curriculum" / course / "lectures"
    files = sorted(p for p in lectures_dir.glob("*.txt"))
    return [p for p in files if len(p.read_text(encoding="utf-8")) >= min_chars]


def _anthropic_batch_texts(
    reqs: dict[str, str], *, model_name: str, max_tokens: int, temperature: float
) -> dict[str, str]:
    """Submit one Anthropic message batch (custom_id -> user prompt) and return
    {custom_id: response text}. Foreground poll; for offline generation only."""
    import time

    import anthropic

    client = anthropic.Anthropic()  # ANTHROPIC_API_KEY from env
    requests = [
        {
            "custom_id": cid,
            "params": {
                "model": model_name,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "system": _SYSTEM,
                "messages": [{"role": "user", "content": prompt}],
            },
        }
        for cid, prompt in reqs.items()
    ]
    batch = client.messages.batches.create(requests=requests)
    print(f"  [submitted Anthropic batch {batch.id}: {len(requests)} passages]")
    waited = 0
    while True:
        b = client.messages.batches.retrieve(batch.id)
        if b.processing_status == "ended":
            break
        if waited >= 24 * 3600:
            raise RuntimeError(f"Anthropic batch {batch.id} did not finish within 24h")
        time.sleep(20)
        waited += 20
    out: dict[str, str] = {}
    for r in client.messages.batches.results(batch.id):
        if r.result.type == "succeeded":
            msg = r.result.message
            out[r.custom_id] = "".join(
                x.text for x in msg.content if getattr(x, "type", None) == "text"
            )
    return out


def generate(
    *,
    course: str,
    num_passages: int,
    questions_per_passage: int,
    model_name: str,
    target_chars: int,
    min_passage_chars: int,
    min_lecture_chars: int,
    seed: int,
    have_counts: dict[str, int] | None = None,
    per_lecture: int | None = None,
    id_offset: int = 0,
    cover_all: bool = False,
    batch: bool = True,
) -> list[dict]:
    """Generate candidate ground-truth rows; see module docstring for the flow.

    *have_counts* maps a lecture stem to how many questions it already has; each
    lecture is topped up only to *per_lecture* (default *questions_per_passage*),
    so ``--append`` re-runs fill deficits without clobbering reviewed rows or
    overshooting the target. New row ids continue from *id_offset*. When
    *cover_all* is set, every still-short lecture is covered and *num_passages*
    is ignored.
    """
    rng = random.Random(seed)
    have_counts = have_counts or {}
    target = per_lecture if per_lecture is not None else questions_per_passage
    lectures = _lecture_files(course, min_lecture_chars)
    if not lectures:
        raise SystemExit(f"No lectures >= {min_lecture_chars} chars for {course}")

    # One passage per still-short lecture; ask only for the deficit so we hit the
    # target exactly and never overshoot.
    rng.shuffle(lectures)
    picks: list[tuple[Path, tuple[int, int, str], int]] = []
    for path in lectures:
        needed = target - have_counts.get(path.stem, 0)
        if needed <= 0:
            continue  # already at/over target — leave it (protects reviewed rows)
        passages = _segment(path.read_text(encoding="utf-8"), target_chars, min_passage_chars)
        if passages:
            picks.append((path, rng.choice(passages), needed))
        if not cover_all and len(picks) >= num_passages:
            break

    prompts = [
        f"Passage from lecture `{p.stem}` (produce up to {need} questions):\n\n{sl.strip()}"
        for p, (_s, _e, sl), need in picks
    ]
    batched: dict[str, str] = {}
    if batch and picks:
        # Default: one Anthropic batch for all passages (~50% cheaper). On any
        # failure the whole set falls back to the live per-passage calls below.
        try:
            batched = _anthropic_batch_texts(
                {str(i): pr for i, pr in enumerate(prompts)},
                model_name=model_name,
                max_tokens=1024,
                temperature=0.7,
            )
        except Exception as exc:  # noqa: BLE001 — degrade to live rather than fail
            print(f"  [batch failed: {exc}; falling back to live]")
            batched = {}

    live_model = None
    rows: list[dict] = []
    seen_questions: set[str] = set()
    n = 0
    for i, (path, (start, end, slice_text), needed) in enumerate(picks):
        content = batched.get(str(i))
        if content is None:
            if live_model is None:
                live_model = ChatAnthropic(model=model_name, temperature=0.7, max_tokens=1024)
            try:
                resp = live_model.invoke(
                    [SystemMessage(content=_SYSTEM), HumanMessage(content=prompts[i])]
                )
            except Exception as exc:  # network/API hiccup — skip this passage, keep going
                print(f"  [skip] {path.stem}: {exc}")
                continue
            content = resp.content if isinstance(resp.content, str) else str(resp.content)
        for item in _parse_json_array(content)[:needed]:
            question = str(item.get("question", "")).strip()
            quote = str(item.get("quote", "")).strip()
            if not question or not quote:
                continue
            key = _norm(question)
            if key in seen_questions:
                continue
            seen_questions.add(key)

            span = _locate(slice_text, quote)
            if span is None:
                # The model paraphrased instead of quoting verbatim, so we can't
                # pin a gold span — drop it rather than emit a gold-less row.
                continue
            n += 1
            row = {
                "id": f"{course[:4]}-{id_offset + n:04d}",
                "course": course,
                "question": question,
                "gold": [
                    {
                        "source": path.name,
                        "start": start + span[0],
                        "end": start + span[1],
                        "quote": slice_text[span[0] : span[1]].strip(),
                    }
                ],
                "topic": path.stem,
                "flags": {
                    **_retrieval_signal(course, question, quote),
                    "needs_review": True,
                },
            }
            rows.append(row)
        print(f"  {path.stem}: {len([r for r in rows if r['topic'] == path.stem])} question(s)")
    return rows


def main() -> int:
    """CLI entry point: parse args, generate rows, write JSONL, print a summary."""
    p = argparse.ArgumentParser(description="Generate a RAG retrieval ground-truth dataset.")
    p.add_argument("--course", default="supply_chain_design")
    p.add_argument("--num-passages", type=int, default=25)
    p.add_argument("--questions-per-passage", type=int, default=2)
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--target-chars", type=int, default=1500)
    p.add_argument("--min-passage-chars", type=int, default=500)
    p.add_argument("--min-lecture-chars", type=int, default=1500)
    p.add_argument("--seed", type=int, default=13)
    p.add_argument("--out", default=None, help="Output JSONL (default: eval/rag_judge/ground_truth/<course>.jsonl)")
    p.add_argument(
        "--append",
        action="store_true",
        help="Merge into the existing JSONL: keep its rows, top up lectures below the "
        "target, and continue the id sequence (preserves reviewed rows).",
    )
    p.add_argument(
        "--per-lecture",
        type=int,
        default=None,
        help="Target questions per lecture (default: --questions-per-passage). In "
        "--append mode, lectures below this are topped up; those at/above are left.",
    )
    p.add_argument(
        "--cover-all",
        action="store_true",
        help="Cover every still-short lecture, one passage each; ignores --num-passages.",
    )
    p.add_argument(
        "--live",
        action="store_true",
        help="Generate synchronously (one live call per passage) instead of the "
             "default Batch API (~2x the cost; use for a quick small run).",
    )
    args = p.parse_args()

    out_path = Path(args.out) if args.out else _REPO_ROOT / "eval" / "rag_judge" / "ground_truth" / f"{args.course}.jsonl"

    from collections import Counter

    existing: list[dict] = []
    have_counts: dict[str, int] = {}
    id_offset = 0
    if args.append and out_path.exists():
        existing = [json.loads(l) for l in out_path.open(encoding="utf-8") if l.strip()]
        have_counts = dict(Counter(r["topic"] for r in existing))
        # Continue ids after the highest existing numeric suffix (ids like "supp-0042").
        id_offset = max(
            (int(r["id"].rsplit("-", 1)[-1]) for r in existing if r.get("id")), default=0
        )
        target = args.per_lecture if args.per_lecture is not None else args.questions_per_passage
        short = sum(1 for _, c in have_counts.items() if c < target)
        print(
            f"Append mode: {len(existing)} existing rows across {len(have_counts)} lectures; "
            f"{short} below target {target}."
        )

    new_rows = generate(
        course=args.course,
        num_passages=args.num_passages,
        questions_per_passage=args.questions_per_passage,
        model_name=args.model,
        target_chars=args.target_chars,
        min_passage_chars=args.min_passage_chars,
        min_lecture_chars=args.min_lecture_chars,
        seed=args.seed,
        have_counts=have_counts,
        per_lecture=args.per_lecture,
        id_offset=id_offset,
        cover_all=args.cover_all,
        batch=not args.live,
    )

    rows = existing + new_rows
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # Keep the human-readable Markdown companion in sync with the JSONL.
    md_path = render_file(out_path, args.course)

    hits = [r for r in new_rows if r["flags"].get("gold_hit")]
    topics = {r["topic"] for r in rows}
    print(
        f"\nWrote {len(new_rows)} new questions ({len(rows)} total) -> {out_path}\n"
        f"  rendered companion -> {md_path}\n"
        f"  new-row gold in top-k (baseline retrieval): {len(hits)}/{len(new_rows)}\n"
        f"  distinct lectures covered (total): {len(topics)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
