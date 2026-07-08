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

## Generating candidates

```
python eval/rag/generate_ground_truth.py --course supply_chain_design \
    --num-passages 25 --questions-per-passage 2
```

The generator (`generate_ground_truth.py`) works **passage → question** so gold
is automatic: it segments each lecture into sentence-aligned passages with exact
offsets, asks Claude for student-voiced questions each with a *verbatim* quote,
locates the quote's span in the source, and records retrieval signals against the
current index. Model defaults to `$ANTHROPIC_MODEL` (or `claude-sonnet-4-6`);
override with `--model`. It's cheap (a Claude call per passage + one embedding
per question) and reproducible via `--seed`.

## Review workflow

Generated rows are **candidates** (`needs_review: true`). Human pass:

1. Confirm the question is genuinely answered by the pinned quote and phrased
   like a real student.
2. Confirm the quote is the *best* passage — if another lecture answers it
   better, fix `gold` (or add a second gold passage).
3. Drop generic questions answerable from many passages.
4. Set `needs_review: false`.

Aim for a ~40-question pilot to validate the pipeline, then scale to ~150–250
spread across lectures (weighted toward exam-relevant topics), including some
multi-passage and some deliberately hard items.

## Harness (planned)

Reads `ground_truth/<course>.jsonl`, runs each question through a RAG system, and
scores span-level overlap: `IoU = |retrieved_chars ∩ gold_chars| /
|retrieved_chars ∪ gold_chars|`, plus recall@k. A retrieved chunk covers gold
when its text overlaps the gold span/quote, so systems with different chunkings
stay comparable.
