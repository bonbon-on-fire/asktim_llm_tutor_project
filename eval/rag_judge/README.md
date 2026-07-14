# RAG retrieval evaluation

Ground-truth dataset + (planned) harness for measuring how well a RAG system
retrieves the *right* lecture passage for a student question.

## Why source-coordinate pinning

Each question is pinned to the lecture passage that answers it using **source
coordinates** — `(lecture file, char span) + verbatim quote` — not chunk ids.
Chunk boundaries shift whenever you re-ingest or swap in a different RAG system,
which would invalidate chunk-id labels. A char span is stable, and the harness
resolves it to whatever chunks the loaded index happens to have. This is what
makes the harness *swappable*: the same labels score any system.

## Dataset schema

`ground_truth/<course>.jsonl` — one JSON object per line:

```jsonc
{
  "id": "supp-0007",
  "course": "supply_chain_design",
  "question": "why does the cheaper supplier not always win once you add shipping?",
  "gold": [                              // 1+ answering passages
    { "source": "lecture_2_3_....txt",   // lecture file (curriculum/<course>/lectures/)
      "start": 4120, "end": 4880,        // char span into that file
      "quote": "…transportation cost scales with distance…" }  // verbatim, human-auditable
  ],
  "topic": "lecture_2_3_...",            // provenance (lecture stem)
  "flags": {
    "gold_hit": true,                    // gold quote appeared in baseline top-k
    "gold_rank": 2,                      // 1-based rank of first covering chunk (null = miss)
    "retrieved_k": 3,
    "top_source": "local:lecture_2_3_...",
    "needs_review": true                 // cleared by a human during review
  }
}
```

`gold_hit=false` rows are **kept on purpose** — they're the hard cases (the
answer exists but the current retriever misses it) that make the eval
discriminating. Questions whose quote can't be located verbatim in the source
(the model paraphrased) are dropped at generation time.

### Readable companion (`<course>.md`)

The JSONL is the source of truth that code reads; a sibling `<course>.md`
renders the same rows in a skimmable form (question, gold quote, source span,
baseline result, review status). The generator writes it automatically, and
`render_markdown.py` regenerates it on demand — run it after editing the JSONL:

```
python eval/rag_judge/render_markdown.py --course supply_chain_design
```

Edit the JSONL, never the `.md` (it's overwritten on every render).

## Generating candidates

```
# Sample N passages across distinct lectures (pilot)
python eval/rag_judge/generate_ground_truth.py --course supply_chain_design \
    --num-passages 25 --questions-per-passage 2

# Full coverage: ~2 questions for EVERY lecture, preserving existing rows
python eval/rag_judge/generate_ground_truth.py --course supply_chain_design \
    --append --cover-all --per-lecture 2 --min-lecture-chars 1000
```

By default this uses the async **Batch API** (Anthropic, ~50% cheaper): one
batch for all sampled passages, polled to completion (minutes–hours). Pass
**`--live`** for one synchronous call per passage (faster to start, ~2× the
cost). Any passage that errors falls back to a live call, so a run never breaks.

The generator (`generate_ground_truth.py`) works **passage → question** so gold
is automatic: it segments each lecture into sentence-aligned passages with exact
offsets, asks Claude for student-voiced questions each with a *verbatim* quote,
locates the quote's span in the source, and records retrieval signals against the
current index. Model defaults to `$ANTHROPIC_MODEL` (or `claude-sonnet-4-6`);
override with `--model`. It's cheap (a Claude call per passage + one embedding
per question) and reproducible via `--seed`.

### Coverage / top-up flags

- `--cover-all` — cover **every** lecture (one passage each), not just
  `--num-passages` of them. Use for full `*_*`-depth coverage.
- `--per-lecture N` — target N questions per lecture (default:
  `--questions-per-passage`). The generator only asks for the *deficit*, so it
  never overshoots the target.
- `--append` — **merge** into the existing JSONL instead of overwriting: keeps
  all existing rows (including human-reviewed ones), tops up only lectures below
  the target, and continues the id sequence. This makes re-runs idempotent —
  running the full-coverage command twice fills any lecture that came up short
  (a generated quote that wasn't verbatim is dropped, so some lectures need a
  second pass to reach the target). Re-run until every lecture hits N; a handful
  of very short lectures may only yield 1 good verbatim-pinned question.

## Review workflow

Generated rows are **candidates** (`needs_review: true`). Human pass:

1. Confirm the question is genuinely answered by the pinned quote and phrased
   like a real student.
2. Confirm the quote is the *best* passage — if another lecture answers it
   better, fix `gold` (or add a second gold passage).
3. Drop generic questions answerable from many passages.
4. Set `needs_review: false`, then re-render the `.md` (see above).

The `supply_chain_design` set has been scaled past the pilot to **full
`*_*`-depth coverage** — ~2 questions for every lecture (~315 rows across ~159
lectures) via `--append --cover-all --per-lecture 2`. The original 42 rows are
human-reviewed (`needs_review: false`); the rest are candidates awaiting the
review pass above. Weight review toward exam-relevant topics, and keep some
multi-passage and deliberately hard items.

## Harness (planned)

Reads `ground_truth/<course>.jsonl`, runs each question through a RAG system, and
scores span-level overlap: `IoU = |retrieved_chars ∩ gold_chars| /
|retrieved_chars ∪ gold_chars|`, plus recall@k. A retrieved chunk covers gold
when its text overlaps the gold span/quote, so systems with different chunkings
stay comparable.
