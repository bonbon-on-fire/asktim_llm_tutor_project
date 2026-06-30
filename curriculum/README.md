# Curriculum

Assignment content used by tutor and student runs, organized by course.

## Structure

```text
curriculum/
  <course_name>/
    course.txt                       # shared course context
    course_name.txt                  # display name shown in the main_ui course banner
    syllabus.txt                     # optional — appended to assignment text in main_ui
    online_link.txt                  # optional — OCW course URL; source for RAG ingestion (Phase 11)
    exercises/                       # assignment prompts
      exercise_01.txt
      exercise_02.txt
      ...
    practices/                       # optional — ungraded practice problems (sandbox_ui)
      practice_01.txt
      practice_02.txt
      ...
    figures/
      exercise_04_power_actors_map.png   # naming: exercise_<NN>_<slug>.png
      ...
    lectures/                        # optional — per-course lecture transcripts
      lecture_01.txt                 # plain text; all included in tutor context
      ...
```

- Each course is a subfolder (for example `cities_and_climate_change/`, `mathematics_for_cs/`).
- `course.txt` stores shared course context.
- `course_name.txt` holds the human-readable course title rendered in the `main_ui/` course banner (via `load_course_name()` in [main_ui/routes/_validation.py](../main_ui/routes/_validation.py)). If empty or absent, the banner renders blank.
- `syllabus.txt` (optional) is appended to the assignment block in `main_ui/`'s context build (see [main_ui/services/tutor_bridge.py](../main_ui/services/tutor_bridge.py)).
- `online_link.txt` (optional) holds the course's MIT OpenCourseWare URL — the canonical source link for **RAG ingestion** of fuller course materials. The [`rag/`](../rag/) pipeline reads it (`python -m rag.ingest --course <c> --source ocw`) to crawl the OCW site's HTML pages **and linked PDFs** (lecture notes, problem sets) into the per-course `rag_index/`. See **Phase 11** in the root [PLANNING.md](../PLANNING.md) and [`rag/README.md`](../rag/README.md).
- `exercises/exercise_XX.txt` stores the assignment prompt for a specific exercise (zero-padded two-digit numbering). Path resolution for all readers (web apps + runners) is centralized in [`utils/curriculum.py`](../utils/curriculum.py).
- `practices/practice_XX.txt` (optional) holds **ungraded practice problems** — a parallel content kind to exercises, selectable as a distinct "Practice problems" group in the `sandbox_ui/` Create-context wizard. Same zero-padded two-digit numbering; resolved via `practices_dir()` / `discover_practice()` in [`utils/curriculum.py`](../utils/curriculum.py).
- `figures/` holds visual context that belongs to a specific exercise. Files must start with `exercise_<NN>_` so the framework (Phase 6 — see root [PLANNING.md](../PLANNING.md)) attaches the matching figures as multimodal input when the tutor/student/judge see that exercise — both in batch runs and in the live AskTIM/Sandbox chat (auto-attached per turn via `services/tutor_bridge.py`). Supported extensions: `.png`, `.jpg`, `.jpeg`. Loaded by [`utils/figures.py`](../utils/figures.py).
- `lectures/` (optional) holds **per-course** lecture transcripts as plain `.txt` files. Every file in the folder is read (sorted by filename, labeled by stem) and folded into the tutor's context for **all** exercises in the course — mirroring how `syllabus.txt` is treated. Loaded by [`utils/lectures.py`](../utils/lectures.py); absent folder = no transcripts.

## Available courses

| Folder | Course | Exercises |
| ------ | ------ | --------- |
| `cities_and_climate_change/` | Cities and Climate Change: Mitigation and Adaptation (MIT 11.270x) | 12 — case study city research + mitigation/adaptation planning; **live in AskTIM for Spring 2026** |
| `intro_to_international_development_planning/` | Introduction to International Development Planning (MIT 11.701) | 24 — 700–800 word reflection prompts |
| `mathematics_for_cs/` | Mathematics for Computer Science (MIT 6.1200J) | 10 — discrete-math problem sets |
| `physics_iii_vibrations_and_waves/` | Physics III: Vibrations and Waves (MIT 8.03SC) | 10 — vibrations/waves problem sets |
| `meaning_of_life/` | The Meaning of Life (MIT 21A.157) | 3 — vignette + investigation + final reflection papers |

The four courses beyond Cities and Climate Change were added in June 2026 as **cross-course test contexts** (two STEM, two humanities) to check how the tutor behaves across subjects. Only `cities_and_climate_change/` is deployed to real students.

## Adding a new course

1. Create a folder under `curriculum/` with the course name.
2. Add `course.txt` with shared context, and `course_name.txt` with the display title for the banner.
3. Optionally add `syllabus.txt` for course-level material that should accompany every exercise.
4. Add an `exercises/` folder with one or more `exercise_XX.txt` files (zero-padded numbering).
5. If an exercise references diagrams or maps, drop them in `figures/` with the `exercise_<NN>_<slug>.<ext>` naming convention.
6. If the course has lecture transcripts, drop plain `.txt` files into `lectures/`; they are included in the tutor context for every exercise in the course.
7. Optionally add `online_link.txt` with the course's MIT OpenCourseWare URL — the source link for RAG ingestion of fuller course materials (see Phase 11 in the root [PLANNING.md](../PLANNING.md)).

## Adding an exercise to an existing course

Add a new `exercises/exercise_XX.txt` file in the course folder. If it has visuals, add matching `figures/exercise_<NN>_*.png` files.
