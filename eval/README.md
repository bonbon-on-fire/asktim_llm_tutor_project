# eval

Evaluation harnesses for the two things we're trying to make better: the **tutor**
(how well it teaches) and the **RAG retrieval** (whether it pulls the right lecture
material). Each lives in its own subfolder with its own README.

## Subfolders

| Folder | Evaluates | What it does | README |
| ------ | --------- | ------------ | ------ |
| [`tutor_judge/`](tutor_judge/) | The **tutor** | LLM-based grader that scores tutor–student transcripts against a rubric (deductions from a 40-point base). Claude is the primary judge. | [tutor_judge/README.md](tutor_judge/README.md) |
| [`rag_judge/`](rag_judge/) | The **RAG retriever** | Ground-truth dataset + (planned) harness that scores retrieval by span-level overlap (IoU / recall@k) against human-pinned lecture passages. | [rag_judge/README.md](rag_judge/README.md) |

## How they differ

- **`tutor_judge` is subjective, end-to-end.** It needs a full simulated
  transcript, then an LLM judge grades the pedagogy. Output is a rubric score
  written back into each transcript's `grade` field.
- **`rag_judge` is objective, retrieval-only.** No transcript needed — it runs a
  question straight through a RAG system and measures how much of the known-correct
  passage was retrieved. The ground truth pins each question to a `(lecture file,
  char span) + verbatim quote`, so the same labels score any swappable RAG system.

Use `tutor_judge` to answer "is the tutor teaching well?" and `rag_judge` to answer
"is retrieval surfacing the right material?" — the latter isolates RAG quality from
the noise of the subjective transcript grade.

## Status

- `tutor_judge` — in use. Latest/recommended: `judge_08` + `rubric_08`.
- `rag_judge` — ground-truth dataset built for `supply_chain_design` (42 validated
  rows at `rag_judge/ground_truth/supply_chain_design.jsonl`); the scoring harness
  is the next major step (see the 2026-07-08 meeting notes).

## Related

- Transcripts graded by `tutor_judge` live in the top-level [`transcripts/`](../transcripts/) folder.
- The RAG system under test lives in [`rag/`](../rag/); course materials in [`curriculum/`](../curriculum/).
