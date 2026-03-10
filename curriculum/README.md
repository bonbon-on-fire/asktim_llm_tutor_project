# Curriculum

Assignment exercises used by both the tutor and student bots. Organized by course.

## Structure

```
curriculum/
  <course_name>/
    course.txt           — course description / shared context
    exercise_01.txt      — individual exercise
    exercise_02.txt
    ...
```

- Each **course** is a subfolder (e.g. `philosophy/`, `urban_studies/`).
- **`course.txt`** contains a course description that provides shared context. It can be prepended to any exercise from that course when passed to the tutor or student.
- **`exercise_XX.txt`** files contain individual assignment prompts.

## Available courses

| Folder | Course | Exercises |
| ------ | ------ | --------- |
| `philosophy/` | Philosophy (ethics, moral reasoning) | 1 — trolley problem / act consequentialism |
| `urban_studies/` | Urban Studies 11.024x (climate action) | 3 — geographic data, stressors, decision actors |

## Adding a new course

1. Create a folder under `curriculum/` with the course name.
2. Add a `course.txt` with the course description.
3. Add `exercise_01.txt`, `exercise_02.txt`, etc.

## Adding an exercise to an existing course

Drop a new `exercise_XX.txt` file into the course folder.
