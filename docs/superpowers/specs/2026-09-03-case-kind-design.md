# Case-study problem kind (`case=N`)

**Date:** 2026-09-03
**Status:** Approved for implementation
**Author:** gautam (bonbon-on-fire) with Claude

## Problem

We want to serve case studies (starting with the "Chef Yourself" SCx cost-out
case) through AskTIM, reachable at a stable URL under an existing course:

```
/embed?course=supply_chain_design&case=1
```

Today the app understands two problem *kinds* — `exercise` (graded) and
`practice` — each with its own content folder, solution folder, URL param, and
validators. A case study is conceptually a third peer of these: it lives beside
a real course's other work, is selected by its own URL param, and (like an
exercise) carries a tutor-only solution/teaching note that must never leak to
the student.

The earlier prototype put the case in a **separate** `supply_chain_case_studies`
course as `exercise_2`. This spec supersedes that: the case moves into the real
`supply_chain_design` course as `case_1`, and the standalone course is removed.

## Goals

- Introduce a third problem kind `case`, a faithful peer of `practice`.
- Content lives at `curriculum/<course>/cases/case_<N>.txt` with tutor-only
  solutions at `curriculum/<course>/cases_solutions/case_solution_<N>.txt`.
- Selectable via `?case=<N>` in **both** `main_ui` and `sandbox_ui` embeds.
- Relocate the Chef Yourself case into `supply_chain_design` and delete the
  standalone `supply_chain_case_studies` course.

## Non-goals

- No wizard/sidebar UI for browsing cases (the `?case=` link is the delivery
  mechanism; a picker can come later). The sandbox context API *may* expose a
  `cases` list for future use, but no JS renders it in this change.
- No new tutor prompt or role — cases reuse the default `tutor` role
  (`tutor_09`); a case is just curriculum content.
- No role-play / dynamic-branching modes (tracked separately).

## Design

### Kind concept

`case` mirrors `practice` everywhere the code branches on kind. The stored
`conversations.exercise_kind` column is free-form `sa.Text()` defaulting to
`"exercise"`, so it already accepts `"case"` — **no migration**.

### Curriculum layer (`utils/curriculum.py`)

New, mirroring the practice helpers:

- `cases_dir`, `case_path`, `case_exists`, `read_case`
- `cases_solutions_dir`
- `discover_cases` (with a `_CASE_NAME_RE = ^case_(\d+)\.txt$`)
- `solution_path` / `read_solution`: add a `kind == "case"` branch →
  `cases_solutions/case_solution_<N>.txt`
- `_SUBPROBLEM_PREFIX`: add `"case": "Case Question"`; `list_subproblems` /
  `subproblem_label` switch to `.get(kind, exercise-prefix)` so a new kind can't
  silently borrow the exercise prefix
- `_DEFAULT_UI_LABELS`: add `"case": "Case {n}"`
- New dispatcher `problem_path(course, number, kind="exercise")` returning the
  exercise/practice/case problem-file path, mirroring the existing
  `solution_path` dispatcher. The two tutor bridges call this instead of an
  inline `practice_path if … else exercise_path` ternary, so the third kind is
  handled in exactly one place.

### Tutor bridges

`ui_core/tutor_bridge.py` and `sandbox_ui/services/tutor_bridge.py` replace their
inline path ternary with `problem_path(course, exercise, kind)`. `read_solution`
and `subproblem_label` are already kind-generic and need no change beyond the
curriculum edits above.

### Validators (both apps' `routes/_validation.py`)

- `validate_case(course, case)` — digit check + `case_exists`, mirroring
  `validate_practice`.
- `validate_selection(course, number, kind)` — add `kind == "case"` arm.
- `resolve_embed_selection(course, raw_exercise, raw_practice, raw_case,
  default_exercise)` — new `raw_case` param. At most one of exercise/practice/
  case may be explicitly supplied (else a `selection` 404); dispatch practice →
  case → exercise(+default).
- sandbox only: `list_cases(course)`, and a `"cases"` entry in
  `list_context_options()` course dicts; `load_selection_preview` /
  `context_exercise` accept `kind == "case"`.

### Routes (both apps)

- `embed.py`: pass `request.args.get("case")` into `resolve_embed_selection`;
  update the module docstring.
- `chat.py`: widen the kind normalization from
  `"practice" if raw == "practice" else "exercise"` to accept `"case"` too
  (`kind if kind in {"practice","case"} else "exercise"`), so a `case`
  conversation persists and streams with the right kind.

### Content relocation

- Add `curriculum/supply_chain_design/cases/case_1.txt` (the Chef Yourself
  case-analysis assignment; `TITLE: Chef Yourself — Case Study`).
- Add `curriculum/supply_chain_design/cases_solutions/case_solution_1.txt` (the
  tutor-only teaching note).
- Delete the `curriculum/supply_chain_case_studies/` course (removes the
  interim `exercise_2` prototype).

## Testing (core)

- `utils/test_curriculum.py`: `case_path`/`case_exists`/`read_case`/
  `discover_cases`/`solution_path(kind="case")`/`problem_path` dispatch.
- Per app, mirror the practice fixtures: a `case=1` embed renders with
  `exerciseKind == "case"`; `validate_case` + `resolve_embed_selection` case
  branch (including the at-most-one guard).
- Offline assembly check: `build_assignment_text(supply_chain_design, "1",
  exercise_kind="case")` splices the case and loads the teaching note as the
  tutor-only solution block.

## Load URL

```
/embed?course=supply_chain_design&case=1
```
`role` defaults to `tutor` (`tutor_09`); no role param needed.
