# rag

Retrieval-Augmented Generation over course materials (Phase 11 — see root
[PLANNING.md](../PLANNING.md)).

Instead of dumping every lecture transcript into every tutor call (~125k tokens,
~17× cost/message for `cities_and_climate_change`), the tutor retrieves only the
handful of chunks relevant to the current student turn.

## What is and isn't ingested

- **Ingested (retrievable):** course description (`course.txt`), syllabus
  (`syllabus.txt`), key concepts (`key_concepts.txt`), lectures
  (`lectures/*.txt`), exercise prompts (`exercises/*.txt`), practice-problem
  prompts (`practices/*.txt`), and OCW content — both HTML pages **and linked
  PDFs** (lecture notes, problem sets, where OCW keeps the substantive material)
  — pulled from the local files, the course's OCW site (`online_link.txt`), or
  both.
- **Never ingested:** the **`*_solutions/` folders** (the current problem's
  solution is paired directly into tutor context — see
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
    chunks = retrieve(course, student_message, k=6)
    block = format_context(chunks)   # injected on the latest student turn
```

## Layout

| File | Role |
| ---- | ---- |
| `chunking.py` | sentence-aware splitter → `Chunk(text, source, course, index)` |
| `embeddings.py` | OpenAI `text-embedding-3-small` batch embedder |
| `store.py` | numpy cosine store (`vectors.npy` + `chunks.jsonl` + `manifest.json`) |
| `sources.py` | local reader: `course.txt` / `syllabus.txt` / `key_concepts.txt` / `lectures/*.txt` / `exercises/*.txt` / `practices/*.txt` (excludes `*_solutions/`) |
| `ocw.py` | OCW crawler (reads `online_link.txt`; HTML via `beautifulsoup4`, linked PDFs via `pypdf`) |
| `ingest.py` | CLI: gather → chunk → embed → save |
| `retrieve.py` | query-time `retrieve()` / `retrieve_scored()` / `to_records()` + `format_context()` |

## Config (env)

- `OPENAI_API_KEY` — required for embedding (ingest + query).
- `EMBEDDING_MODEL` — defaults to `text-embedding-3-small`.

## Notes

- Vector store is brute-force numpy cosine (instant at the few-hundred-to-~1k
  chunks/course seen so far, no FAISS dependency); `pgvector` on the production
  Postgres is the eventual swap.
- Re-run `rag.ingest` when course materials change (the manifest records source
  hashes so staleness is detectable).
