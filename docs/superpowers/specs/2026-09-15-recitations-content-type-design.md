# Recitations as a first-class content type + add MIT 15.C57 Optimization course

Date: 2026-09-15
Status: Approved-pending-review

## Problem

The curriculum content model treats **lectures** as a first-class, RAG-indexed,
citeable type (`lectures/*.txt` + `lecture_index.json`). Recitations have no
home: in `supply_chain_fundamentals`, 19 recitation videos were shoehorned into
`lectures/` as `lecture_<w>_<seq>_recitation_..._video_N.txt`, so they cite as
"Lecture X.Y" instead of "Recitation …", and there is nowhere to put the
recitation material for the new MIT 15.C57 Optimization course.

Goal: make **recitations** a parallel first-class type — its own folder, its own
index, RAG-retrievable, correctly cited — then retrofit the one existing course
that needs it, then build the C57 course on the new structure.

## Non-goals

- No change to how lectures, readings, practices, exercises, or pinned docs work.
- No renumbering of lecture sequences.
- No new UI surface beyond mirroring the existing sandbox lectures toggle.
- No solutions authored for C57 (none were provided; README-only, per decision).

## Current architecture (5 coupling points for lectures)

1. **Files + index:** `curriculum/<course>/lectures/*.txt` and
   `curriculum/<course>/lecture_index.json` (per-file → `{week, lesson/session,
   section, video, video_title, citation}`).
2. **Ingestion** — `rag/sources.py::load_local_docs`: ingests `lectures/`,
   `readings/`, `practices/` as `local:<stem>` docs. Excludes pinned/exercises/
   solutions/figures/rag_index/metadata.
3. **Retrieval** — `rag/retrieve.py`:
   - `_WEEK_RE = ^local:(?:lecture|practice|exercise|reading)_(\d+)` scopes
     retrieval to weeks the student has reached.
   - `_source_label` renders citations; when a `lecture_index.json` entry exists
     it uses the entry's `citation`, else falls back to `_LECTURE_RE` etc.
4. **Context fold** — `utils/lectures.py::load_lecture_transcripts`: concatenates
   all `lectures/*.txt` for full_context mode.
5. **Bridges** — `ui_core/tutor_bridge.py` and `sandbox_ui/services/tutor_bridge.py`
   call the loader; folded only when `context_mode == "full_context"`.

**Context-mode reality:** `rag` is the default whenever a course has an index and
no custom pasted context (`_resolve_context_mode`, ui_core/tutor_bridge.py:143).
`full_context` is a fallback (no index) / sandbox-custom-context path. So in
production, recitations are reached via RAG. The full_context fold is mirrored
for parallelism and to keep the fallback correct, but is not the hot path.

## Design

### 1. New content type `recitations/`

- Files: `curriculum/<course>/recitations/recitation_<week>_<seq>_<slug>.txt`.
  Week-first so week-scoping works unchanged. `<seq>` orders within the course.
- Index: `curriculum/<course>/recitation_index.json` — **identical schema** to
  `lecture_index.json`. Keys are `local:recitation_<week>_<seq>_<slug>`.
- Source label at ingest: `local:recitation_<week>_<seq>_<slug>`.

### 2. Ingestion (`rag/sources.py`)

Add `"recitations"` to the retrievable-subdir loop:
`for subdir in ("lectures", "recitations", "readings", "practices")`.
Update the module docstring to list recitations. No other change.

### 3. Retrieval (`rag/retrieve.py`)

- `_WEEK_RE`: add `recitation` to the alternation →
  `^local:(?:lecture|recitation|practice|exercise|reading)_(\d+)`.
- Citation lookup: recitation entries live in `recitation_index.json`. Add a
  `_recitation_index(course)` loader (cached, same shape as `_lecture_index`) and
  have `_source_label` consult it as well — cleanest as a small
  `_citation_index(course)` that merges both dicts (keys never collide: `lecture_`
  vs `recitation_` prefixes). Merge is what `_source_label` reads for the
  `entry["citation"]` override.
- Fallback label: add
  `_RECITATION_RE = ^local:recitation_(\d+)_(\d+)_(.+)$` →
  `"Recitation {w}.{s} {Titleized}"`, mirroring `_LECTURE_RE`. Used only when a
  course ships recitation files without an index entry.

### 4. Context fold (`utils/lectures.py`)

Add `load_recitation_transcripts(course, curriculum_root=None)`, a copy of
`load_lecture_transcripts` reading `recitations/*.txt` with the same natural-sort
`_natural_key`. Returns `""` when the folder is absent (additive/backward-safe).
(Factor the shared body into a private `_load_transcripts(course, subdir, root)`
helper so lectures and recitations don't drift.)

### 5. Bridges

In both `ui_core/tutor_bridge.py` and `sandbox_ui/services/tutor_bridge.py`,
wherever lecture transcripts are folded (full_context only), also fold
recitations as a `"Recitation transcripts:\n" + …` block when non-empty.
- sandbox_ui: gate recitations under the **same** `include_lectures` toggle
  (it means "include taught transcripts"); no new DB column, no new wizard field.
  Update the toggle's doc comment to say lectures + recitations.

### 6. Tests

Mirror existing lecture coverage:
- `rag/test_lecture_index.py`: also discover `*/recitation_index.json`, validate
  non-empty, schema-consistent, and that every `recitations/*.txt` has an entry
  and every entry has a file (mirror whatever the lecture assertions do).
- `rag/test_week_scope.py`: add a `recitation_2_...` source scopes to week 2 case.
- `rag/test_sources.py`: assert `recitations/*.txt` is ingested; a `_solutions/`
  / pinned exclusion still holds.
- `utils/test_lectures.py` (or new `utils/test_recitations.py`): cover
  `load_recitation_transcripts` present/absent/empty + natural-sort order.

### 7. Migration — `supply_chain_fundamentals` only

Confirmed the only affected course: 19 files named
`lecture_<w>_<seq>_recitation_<slug>_video_N.txt`, each already index-tagged
`section: "Recitation: …"`. (SC design's 28 "recitation" hits are body-text
mentions in real lectures — 0 recitation filenames/index entries — so it is NOT
migrated. A classifier over filename token AND index `section` prefix is run
across all courses to confirm no others qualify.)

Steps:
1. Move the 19 files `lectures/ → recitations/`, renaming
   `lecture_<w>_<seq>_recitation_<slug>_video_N.txt` →
   `recitation_<w>_<seq>_<slug>_video_N.txt` (drop the redundant `recitation`
   word; keep original `<w>` and `<seq>` to preserve order and week-scope).
2. Move the 19 entries out of `lecture_index.json` into a new
   `recitation_index.json`, rekeying `local:lecture_<w>_<seq>_recitation_…` →
   `local:recitation_<w>_<seq>_…`. Entry values unchanged (already correct
   `section`/`video`/`citation`).
3. Re-ingest: `python -m rag.ingest --course supply_chain_fundamentals
   --source local`. Source labels change, so chunks/vectors/manifest rebuild
   (~761 chunks re-embed, text-embedding-3-small, a few cents). doc_count and
   text unchanged; only labels/locations move.
4. Commit migration + regenerated `rag_index/`.

### 8. Build MIT 15.C57 Optimization — `curriculum/optimization_methods/`

Mirrors the minimal `machine_learning_optimization` template (no key_concepts,
no online_link, no ui_labels, no tutor_rules):
- `course_name.txt` — e.g. "MIT 15.C57 Optimization" (Common Ground subject).
- `pinned/course.txt` — course-description prose (from syllabus "Course
  Contents").
- `pinned/syllabus.txt` — plain-text syllabus (instructors, TAs, schedule,
  grading 20/20/20/30/10, HW table, policies), mirroring ML-opt's syllabus.txt.
- `lectures/lecture_1_<slug>.txt` from the 53-page Lecture 1 deck +
  `lecture_index.json` (1 entry).
- `recitations/recitation_1_<slug>.txt` from Recitation 1 +
  `recitation_index.json` (1 entry).
- `exercises/exercise_1.txt` — faithful transcription of HW1 (4 problems) +
  `exercises_solutions/README.txt` (tutor-only, no answers; mirror ML-opt README).
  HW1 CSV data files excluded (students get them on Canvas; RAG doesn't index
  data).
- `rag_index/` via `python -m rag.ingest --course optimization_methods
  --source local`.

## Sequencing / commits (commit as you go)

1. `feat(rag): add recitations as a first-class RAG content type` — sources,
   retrieve, utils/lectures, both bridges, tests.
2. `refactor(supply_chain_fundamentals): split recitations out of lectures` —
   file moves, index split, regenerated rag_index.
3. `feat(optimization_methods): add MIT 15.C57 Optimization course` — course
   files + rag_index.

## Risks

- **Re-embedding cost/time** for SC fundamentals reindex — small (~761 chunks).
- **Index/file drift** — the extended `test_lecture_index.py` enforces the
  file↔entry bijection for recitations too, catching a missed rename.
- **Citation regression** — mitigated by keeping recitation entries' existing
  `citation` strings verbatim during migration.
