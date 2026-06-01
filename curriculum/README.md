# Curriculum

Assignment content used by tutor and student runs, organized by course.

## Structure

```text
curriculum/
  <course_name>/
    course.txt                       # shared course context
    syllabus.txt                     # optional — appended to assignment text in main_ui
    exercise_01.txt                  # assignment prompt
    exercise_02.txt
    ...
    figures/
      exercise_04_power_actors_map.png   # naming: exercise_<NN>_<slug>.png
      ...
```

- Each course is a subfolder (for example `philosophy/`, `cities_and_climate_change/`).
- `course.txt` stores shared course context.
- `syllabus.txt` (optional) is appended to the assignment block in `main_ui/`'s context build (see [main_ui/services/tutor_bridge.py](../main_ui/services/tutor_bridge.py)).
- `exercise_XX.txt` stores the assignment prompt for a specific exercise.
- `figures/` holds visual context that belongs to a specific exercise. Files must start with `exercise_<NN>_` so the framework (Phase 6 — see root [PLANNING.md](../PLANNING.md)) can attach the matching figures when the tutor sees that exercise.

## Available courses

| Folder | Course | Exercises |
| ------ | ------ | --------- |
| `cities_and_climate_change/` | Cities and Climate Change: Mitigation and Adaptation (I, II and III) | 12 — case study city research + mitigation/adaptation planning; live in AskTIM for Spring 2026 |
| `philosophy/` | Philosophy (ethics, moral reasoning) | 1 — trolley problem / act consequentialism |
| `intl_dev_planning/` | International Development Planning | preview / scaffold |
| `social_theory_city/` | Social Theory and the City | preview / scaffold |
| `sustainable_econ_dev/` | Sustainable Economic Development | preview / scaffold |

## Adding a new course

1. Create a folder under `curriculum/` with the course name.
2. Add `course.txt` with shared context.
3. Optionally add `syllabus.txt` for course-level material that should accompany every exercise.
4. Add one or more `exercise_XX.txt` files (zero-padded numbering).
5. If an exercise references diagrams or maps, drop them in `figures/` with the `exercise_<NN>_<slug>.<ext>` naming convention.

## Adding an exercise to an existing course

Add a new `exercise_XX.txt` file in the course folder. If it has visuals, add matching `figures/exercise_<NN>_*.png` files.
