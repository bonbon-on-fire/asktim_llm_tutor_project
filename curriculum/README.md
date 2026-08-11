# Curriculum

Assignment content used by tutor and student runs, organized by course.

## Structure

```text
curriculum/
  <course_name>/
    course_name.txt                  # display name shown in the main_ui course banner
    tutor_rules.txt                  # optional — course-specific tutor rules appended to the base prompt
    online_link.txt                  # optional — OCW course URL; source for RAG ingestion (Phase 11)
    key_concepts.txt                 # optional — condensed course concepts; retrievable via RAG
    pinned/                          # always-pinned reference docs (folded into context; NOT retrieved)
      course.txt                     # course description (first line is its title)
      syllabus.txt                   # optional — course syllabus
      optimization_debugging_flowchart.txt   # optional — any other course reference doc
      ...
    exercises/                       # assignment prompts
      exercise_1.txt
      exercise_2.txt
      ...
    exercises_solutions/             # optional — reference solutions, one per exercise
      exercise_solution_1.txt        # naming: exercise_solution_<N>.txt (mirrors exercise_<N>.txt)
      ...
    practices/                       # optional — ungraded practice problems (sandbox_ui)
      practice_1.txt
      practice_2.txt
      ...
    practices_solutions/             # optional — reference solutions, one per practice
      practice_solution_1.txt        # naming: practice_solution_<N>.txt (mirrors practice_<N>.txt)
      ...
    figures/
      exercise_4_power_actors_map.png    # naming: exercise_<N>_<slug>.png
      ...
    lectures/                        # optional — per-course lecture transcripts
      lecture_1_0_intro.txt          # plain text; all included in tutor context
      ...
    lecture_index.json               # optional — maps each lecture stem to its real Week/Lesson/Video citation
    rag_index/                       # optional — built RAG index (vectors.npy + chunks.jsonl + manifest.json)
  _archive/                          # archived courses — hidden from the apps, still readable by tooling
    <course_name>/                   # same layout as an active course
```

- Each course is a subfolder (for example `cities_and_climate_change/`, `mathematics_for_cs/`).
- `course_name.txt` holds the human-readable course title rendered in the `main_ui/` course banner (via `load_course_name()` in [main_ui/routes/_validation.py](../main_ui/routes/_validation.py)). If empty or absent, the banner renders blank.
- `pinned/` holds **always-pinned reference docs** — every `pinned/*.txt` is folded directly into the tutor's context in `full_context` and `rag` modes, and is **excluded from the RAG index** (never retrieved), so nothing pinned is also re-fetched by retrieval. This is where the **course description (`pinned/course.txt`)**, the **syllabus (`pinned/syllabus.txt`)**, and any other always-on material (e.g. a Solver debugging flow chart) live. Each file carries its own title as its first line; they're read (sorted, stripped, blank-line-joined) by `read_pinned_context()` in [`utils/curriculum.py`](../utils/curriculum.py) and folded in by `build_assignment_text` ([ui_core/tutor_bridge.py](../ui_core/tutor_bridge.py)); the exclusion from retrieval is in [rag/sources.py](../rag/sources.py). `read_course_description()` is a single-doc accessor for `pinned/course.txt` (the lean judge-context in the runners).
- `tutor_rules.txt` (optional) holds **course-specific tutor rules** appended to the base tutor prompt (`tutor_08`) whenever the course has one — so a course can tune tutor behavior (e.g. "assume spreadsheets over Python") without forking a whole prompt version. Read + appended by `read_course_tutor_rules()` / `append_course_tutor_rules()` in [`utils/curriculum.py`](../utils/curriculum.py); applied in both apps (via `build_system_prompt`) and the bulk-simulation runners so evals mirror production. (Unlike `pinned/*.txt`, this is a system-prompt delta, not context body — so it lives at the course top level, not under `pinned/`.)
- `online_link.txt` (optional) holds the course's MIT OpenCourseWare URL — the canonical source link for **RAG ingestion** of fuller course materials. The [`rag/`](../rag/) pipeline reads it (`python -m rag.ingest --course <c> --source ocw`) to crawl the OCW site's HTML pages **and linked PDFs** (lecture notes, problem sets) into the per-course `rag_index/`. See **Phase 11** in the root [PLANNING.md](../PLANNING.md) and [`rag/README.md`](../rag/README.md).
- `exercises/exercise_X.txt` stores the assignment prompt for a specific exercise (non-padded numbering — `exercise_1.txt`, `exercise_10.txt`). Path resolution for all readers (web apps + runners) is centralized in [`utils/curriculum.py`](../utils/curriculum.py), which normalizes numbers and sorts them numerically. `01` and `1` both resolve to `exercise_1.txt`.
- `practices/practice_X.txt` (optional) holds **ungraded practice problems** — a parallel content kind to exercises, selectable as a distinct "Practice problems" group in the `sandbox_ui/` Create-context wizard. Same non-padded numbering; resolved via `practices_dir()` / `discover_practice()` in [`utils/curriculum.py`](../utils/curriculum.py).
- `figures/` holds visual context that belongs to a specific exercise. Files must start with `exercise_<N>_` so the framework (Phase 6 — see root [PLANNING.md](../PLANNING.md)) attaches the matching figures as multimodal input when the tutor/student/judge see that exercise — both in batch runs and in the live AskTIM/Sandbox chat (auto-attached per turn via `services/tutor_bridge.py`). Supported extensions: `.png`, `.jpg`, `.jpeg`. Loaded by [`utils/figures.py`](../utils/figures.py).
- `lectures/` (optional) holds **per-course** lecture transcripts as plain `.txt` files. Every file in the folder is read (sorted by filename, labeled by stem). In `full_context` mode they're all folded into the tutor's context; in `rag` mode (the default) they're **retrievable via RAG** instead (too large to pin). Loaded by [`utils/lectures.py`](../utils/lectures.py); absent folder = no transcripts.
- `key_concepts.txt` (optional) holds a condensed distillation of the course's key concepts. It is **retrievable via RAG** (chunked + embedded by [`rag/`](../rag/)) — too large to pin, unlike the `pinned/` docs (course description, syllabus) which are folded into context and excluded from retrieval.
- `exercises_solutions/` and `practices_solutions/` (optional) hold **reference solutions**, one file per exercise/practice named `exercise_solution_<N>.txt` / `practice_solution_<N>.txt` (same non-padded numbering as the problem it mirrors — the `_solution_` infix keeps solution files from colliding with problem filenames). They are **paired directly into the tutor's context** for the current problem (a tutor-only correct-answer input) and are deliberately **excluded from the RAG index** so a solution is never surfaced by similarity. Resolved via `read_solution()` in [`utils/curriculum.py`](../utils/curriculum.py).
- `lecture_index.json` (optional) maps each `lectures/*.txt` stem to its **true course coordinates** — `week`, `lesson`, `video`, `video_title`, and a ready-to-render `citation` string (e.g. `"Week 10, Lesson 1 · Video 7: DuPont Analysis"`). Built by scraping the live course structure (edX blocks API), it lets the tutor cite a lecture by a location a student can actually find, instead of the synthetic `lecture_<week>_<seq>` file stem. Consumed by `_source_label()` in [`rag/retrieve.py`](../rag/README.md); a validation test asserts every entry resolves to a real lecture file.
- `rag_index/` (optional) holds the **built RAG index** for the course (`vectors.npy` + `chunks.jsonl` + `manifest.json`), produced by `python -m rag.ingest` and committed so deploys don't re-embed. See [`rag/README.md`](../rag/README.md).

## Available courses

| Folder | Course | Exercises |
| ------ | ------ | --------- |
| `cities_and_climate_change/` | Cities and Climate Change: Mitigation and Adaptation (MIT 11.270x) | 12 — case study city research + mitigation/adaptation planning; **live in AskTIM for Spring 2026** |
| `economic_development_planning/` | Economic Development Planning (MIT 11.438) | 4 — two professional memos (Deputy Mayor role), a midterm lens/tool paper, and a community-engaged final case study; also ships 17 `lectures/` transcripts and a `lecture_index.json` of Session/Unit citations |
| `intro_to_international_development_planning/` | Introduction to International Development Planning (MIT 11.701) | 24 — 700–800 word reflection prompts |
| `mathematics_for_cs/` | Mathematics for Computer Science (MIT 6.1200J) | 10 — discrete-math problem sets |
| `physics_iii_vibrations_and_waves/` | Physics III: Vibrations and Waves (MIT 8.03SC) | 17 — 10 problem sets, 5 practice exams, and the 2 real Fall 2016 exams; also ships 24 `lectures/` transcripts, a `lecture_index.json`, and `exercises_solutions/` for the 5 practice exams (OCW publishes no solutions for the problem sets or the real exams) |
| `meaning_of_life/` | The Meaning of Life (MIT 21A.157) | 3 — vignette + investigation + final reflection papers |
| `supply_chain_design/` | MIT CTL.SC2x Supply Chain Design | 8 graded exercises (weeks 1–10, non-consecutive) — network/facility-location, production-planning, and supply-chain-finance assignments; also ships 8 ungraded `practices/`, 160 `lectures/` transcripts, and a `lecture_index.json` of real Week/Lesson/Video citations |
| `urban_transportation/` | Urban Transportation, Land Use, and the Environment (MIT 11.943J) | 4 — issue papers + a Mexico City / Santiago case-study consulting exercise; also ships 10 `lectures/` transcripts and a `lecture_index.json` of Lecture citations |

All eight courses above are currently **active**. Archived courses, if any, live
under `_archive/` and are listed by `list_archived_courses()` in
[`utils/curriculum.py`](../utils/curriculum.py).

The four courses beyond Cities and Climate Change (Development Planning, Mathematics for CS, Physics III, and Meaning of Life) were added in June 2026 as **cross-course test contexts** (two STEM, two humanities) to check how the tutor behaves across subjects. `supply_chain_design/` (MIT CTL.SC2x) was added later as a lecture-heavy course. Only `cities_and_climate_change/` is deployed to real students.

## Adding a new course

1. Create a folder under `curriculum/` with the course name.
2. Add `course_name.txt` with the display title for the banner, and `pinned/course.txt` with the course description (its first line is the doc's title, e.g. `Course description`).
3. Optionally add `pinned/syllabus.txt` (and any other always-in-context reference doc) under `pinned/` — each is folded into the tutor context every turn.
4. Add an `exercises/` folder with one or more `exercise_X.txt` files (non-padded numbering).
5. If an exercise references diagrams or maps, drop them in `figures/` with the `exercise_<N>_<slug>.<ext>` naming convention.
6. If the course has lecture transcripts, drop plain `.txt` files into `lectures/`; they are included in the tutor context for every exercise in the course.
7. Optionally add `online_link.txt` with the course's MIT OpenCourseWare URL — the source link for RAG ingestion of fuller course materials (see Phase 11 in the root [PLANNING.md](../PLANNING.md)).
8. Optionally add `tutor_rules.txt` with course-specific tutor rules — they're appended to the base prompt for this course only (no per-course prompt fork). Include a **"Problem shorthand:"** bullet that maps how students abbreviate this course's problems (e.g. `PP2` → Practice Problem 2, `A2` → Assignment 2) to the numbered `exercises/`/`practices/` files. Every course uses this same bullet shape — anchored to the `exercise_N` / `practice_N` numbering rather than the (per-course-varying) title words — so the tutor resolves student shorthand consistently across courses.

## Archiving a course

Archived courses stay in the repo but disappear from the apps: the sandbox
context switcher stops listing them and `validate_course` rejects their slug, so
their embed URLs return 404.

1. Move the folder: `git mv curriculum/<course> curriculum/_archive/<course>`.
2. Confirm no app still defaults to it — `DEFAULT_COURSE` in
   [main_ui/routes/_validation.py](../main_ui/routes/_validation.py) and
   [sandbox_ui/routes/_validation.py](../sandbox_ui/routes/_validation.py). The
   `test_validation_archive` standalone tests assert this.
3. Commit. The course's `rag_index/` moves with it, since the index is a child
   of the course folder — it stays right where offline tooling can still read it.

Existing conversations that reference an archived course still render in
`database_ui` — its display-name map is hardcoded and never reads `curriculum/`.

Offline tooling still reaches an archived course by explicit slug (for example
the eval runners, or reading its `rag_index/` directly), because `course_dir()`
falls back to `curriculum/_archive/<course>/`. Only discovery and validation
change. `rag.ingest` is the one exception: it deliberately refuses an archived
slug (`parser.error`, exit 2) rather than silently rebuilding an index for a
retired course — unarchive the course first if you need to re-ingest it.
In both apps, `validate_course()` rejects an archived slug before any
course-relative path is resolved, so the apps themselves never read from
`_archive/`.

To unarchive, move the folder back.

## Adding an exercise to an existing course

Add a new `exercises/exercise_X.txt` file in the course folder. If it has visuals, add matching `figures/exercise_<N>_*.png` files.
