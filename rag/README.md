# rag

Retrieval-Augmented Generation over course materials (Phase 11 — see root
[PLANNING.md](../PLANNING.md)).

Instead of dumping every lecture transcript into every tutor call (~125k tokens,
~17× cost/message for `cities_and_climate_change`), the tutor retrieves only the
handful of chunks relevant to the current student turn.

## What is and isn't ingested

- **Ingested (retrievable):** course description (`course.txt`), syllabus
  (`syllabus.txt`), key concepts (`key_concepts.txt`), lectures
  (`lectures/*.txt`), practice-problem prompts (`practices/*.txt`), and OCW
  content — both HTML pages **and linked PDFs** (lecture notes, problem sets,
  where OCW keeps the substantive material) — pulled from the local files, the
  course's OCW site (`online_link.txt`), or both.
- **Never ingested:** the **`exercises/*.txt` graded-problem prompts** (the
  exercise the student is on is paired directly into tutor context, so retrieval
  must never surface it or any *other* graded exercise), the **`*_solutions/`
  folders** (the current problem's solution is paired the same way — see
  `utils.curriculum.read_solution` — never surfaced by similarity), **figures**
  (`figures/`, handled by the multimodal pipeline), and metadata files
  (`course_name.txt`, `online_link.txt`).

## Build an index

```powershell
# from the repo root
python -m rag.ingest --course cities_and_climate_change --source local
python -m rag.ingest --course mathematics_for_cs        --source ocw
python -m rag.ingest --course <course>                  --source both
```

`--source` is a toggle: `local` (curriculum files), `ocw` (crawl the course's
`online_link.txt` — HTML pages **and linked PDFs**), or `both`. OCW needs
`beautifulsoup4` (HTML) and `pypdf` (PDF text). Output lands in
`curriculum/<course>/rag_index/` (`vectors.npy` + `chunks.jsonl` +
`manifest.json`) and is meant to be committed so deploys don't re-embed.

> **OCW notes.** The crawler follows in-scope links under `/courses/<slug>/`,
> extracts text from HTML pages, and downloads + text-extracts linked PDFs (the
> real lecture/problem-set content). PDF text extraction is best-effort — math
> notation can come out imperfectly — and **scanned/image-only PDFs are not
> OCR'd**. For courses with clean local transcripts (e.g. cities_and_climate_change),
> `--source local` gives richer content than the OCW HTML alone.

## Retrieve (used by the tutor)

```python
from rag import retrieve, format_context, has_index

if has_index(course):
    chunks = retrieve(course, student_message, k=6, max_week=4)
    block = format_context(chunks, course)   # injected on the latest student turn
```

### Citation labels (`lecture_index.json`)

Each retrieved chunk is labeled in the injected block so the tutor can cite it.
`format_context(chunks, course)` resolves a chunk's source to a human label via
`_source_label`: if the course ships `curriculum/<course>/lecture_index.json`
and the source is in it, the label is the chunk's **real Week / Lesson / Video
coordinate** (e.g. `[Week 10, Lesson 1 · Video 7: DuPont Analysis]`) — a location
a student can actually find on the course site. Without an index (or for
non-lecture sources), it falls back to a stem-derived label (`Lecture 10.6 …`,
`Practice 4`, `Syllabus`). The index is built by scraping the live course
structure; see the `curriculum/` README. Passing `course` is what activates the
real labels — omit it (older callers) and you get the fallback.

### Week-scoped retrieval (`max_week`)

Lecture and practice sources encode the course **week** as their first number
(`lecture_2_3_...` → week 2, `practice_4` → week 4). Passing `max_week=N` drops
any lecture/practice material from a **later** week than `N` before the top-k is
taken, so the tutor never surfaces content the student hasn't reached. The tutor
bridge passes the current problem's number as `max_week` (exercise/practice
numbers share the lecture week number). Week-agnostic docs — course description,
syllabus, key concepts, OCW content — carry no week and are always in scope.
Omit `max_week` (the default) to retrieve across all weeks.

## Layout

| File | Role |
| ---- | ---- |
| `chunking.py` | sentence-aware splitter → `Chunk(text, source, course, index)` |
| `embeddings.py` | OpenAI `text-embedding-3-small` batch embedder |
| `store.py` | numpy cosine store (`vectors.npy` + `chunks.jsonl` + `manifest.json`) |
| `sources.py` | local reader: `course.txt` / `syllabus.txt` / `key_concepts.txt` / `lectures/*.txt` / `practices/*.txt` (excludes `exercises/*.txt` and `*_solutions/`) |
| `ocw.py` | OCW crawler (reads `online_link.txt`; HTML via `beautifulsoup4`, linked PDFs via `pypdf`) |
| `ingest.py` | CLI: gather → chunk → embed → save |
| `retrieve.py` | query-time `retrieve()` / `retrieve_scored()` / `to_records()` + `format_context()`; `_source_label()` renders citeable labels from `lecture_index.json` |

## Config (env)

- `OPENAI_API_KEY` — required for embedding (ingest + query).
- `EMBEDDING_MODEL` — defaults to `text-embedding-3-small`.

## Notes

- Vector store is brute-force numpy cosine (instant at the few-hundred-to-~1k
  chunks/course seen so far, no FAISS dependency); `pgvector` on the production
  Postgres is the eventual swap.
- Re-run `rag.ingest` when course materials change (the manifest records source
  hashes so staleness is detectable).
