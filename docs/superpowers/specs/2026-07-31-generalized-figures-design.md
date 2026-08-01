# Generalized Figures — Design

**Date:** 2026-07-31
**Status:** Approved (pending spec review)

## Problem

The codebase already sends curriculum figures to the multimodal models as **vision
content** (base64 `data:` URLs), not merely as text references. But discovery and
wiring are hardcoded to **graded exercises**:

- `utils/figures.py` matches only `^exercise_(\d+)_.+\.(png|jpe?g)$`.
- `discover_figures(course, exercise_number)` keys on an exercise number.
- Callers wire it only for exercises, e.g.
  `internal_testing/run_transcript_rag.py`:
  `figures = discover_figures(...) if config.kind == "exercise" else []`
  ("Figures only apply to graded exercises").

So a lecture that has a figure (e.g. the urban_transportation "Induced Demand"
graph or the "Two Cities" comparison) cannot show that figure to the tutor. We want
figures to work for **lectures** and **practices** too, reusing the existing vision
plumbing.

## Key architectural fact

Exercises and lectures enter the tutor by different paths:

- **Exercise:** exactly one is "active" per conversation → its figures attach
  cleanly to that one human message, and can be bound **once** at graph
  construction (today's behavior).
- **Lectures / practices:** reach the tutor via **per-turn RAG retrieval**
  (`rag.retrieve`). There is no single "active lecture." Retrieved chunks carry a
  source label `local:<stem>` (e.g. `local:lecture_5_...`), and
  `rag/retrieve.py` already maps a source label → its number
  (`_source_week()` + `lecture_index.json`).

**Decision (user):** lecture/practice figures attach **only when that item's chunk
is retrieved for the current turn** — precise and cost-controlled. This makes those
figures inherently **per-turn**, so they must flow through the tutor graph like
`retrieved_context` does, not through the constructor closure.

## Approach (chosen: A — generalize the convention)

Considered: (A) generalize the naming convention + per-turn figures; (B) a separate
standalone lecture-figures path; (C) a per-course `figures.json` manifest. Chose A:
it matches the convention that already exists, keeps exercises byte-for-byte
unchanged, and reuses the source→number mapping already in `retrieve.py`. B
duplicates logic into two divergent systems; C's flexibility (arbitrary slugs, one
figure shared across items) is YAGNI now.

## Design

### 1. Naming convention

`<kind>_<id>_<slug>.<png|jpg|jpeg>`, where `kind ∈ {exercise, lecture, practice}`
and `id` is the number in the sibling `.txt` stem (e.g. `lecture_5_...` →
`figures/lecture_5_two_cities.png`). Existing exercise figures
(`exercise_4_power_actors_map.png`) are unchanged.

### 2. `utils/figures.py`

- Widen the name regex to `^(exercise|lecture|practice)_(\d+)_.+\.(png|jpe?g)$`,
  capturing `(kind, id)`.
- Keep `discover_figures(course, exercise_number)` behavior identical — it
  continues to return **only** `exercise_<N>_*` figures (delegates internally to
  `kind="exercise"`). Every existing caller keeps working untouched.
- Add `discover_figures_for_sources(course, sources, curriculum_root=None) ->
  list[Path]`: given retrieved chunk source labels (`local:lecture_5_...`,
  `local:practice_3_...`), parse `(kind, id)` from each and return the matching
  figures under `<course>/figures/`. Deduped, stable (sorted) order. Non-item
  sources (e.g. `local:key_concepts`) yield nothing.
- `build_multimodal_content()` and `_attach_figures_to_last_human()` are
  unchanged — they already accept any list of figure paths.
- Update the module docstring: a figure serves exactly one **content item**
  (exercise, lecture, or practice), not "exactly one exercise."

### 3. Per-turn wiring (the one behavioral change)

- `tutor/run_tutor.py`: `TutorState` gains an optional `turn_figures: list` field.
  `tutor_node` attaches the **union** of `figures` (static, exercise, from the
  closure) and `state["turn_figures"]` (per-turn, retrieved) to the last human
  message, deduped, preserving order (exercise figures first). When both are
  empty, behavior is exactly as today.
- `internal_testing/run_transcript_rag.py`: after `rc = _retrieved_context(...)`,
  compute
  `turn_figures = discover_figures_for_sources(config.course, [r["source"] for r in rc.records])`
  and pass it into the graph invoke alongside `retrieved_context`. The STEM arm
  (no retrieval) passes an empty list.

### 4. Non-RAG paths (full_context / no index)

These do not retrieve, so they receive no lecture/practice figures — consistent
with "only when retrieved." Exercise figures still attach as today. No change.

### 5. Judge replay (`eval/tutor_judge/run_judge.py`) — match the tutor

The judge grades the whole conversation as one block using a top-level `figures`
list (currently the static exercise set). To see exactly what the tutor saw, it
must also **union in the per-turn lecture/practice figures** reconstructed from each
exchange's persisted `retrieved` records:

- Gather every `exchanges[*].retrieved[*].source`, run them through
  `discover_figures_for_sources(course, sources)`, union with the static exercise
  figures, dedupe, and resolve to paths (`figure_filenames` /
  `resolve_figure_filenames` for the transcript round-trip).
- `run_transcript_rag.py`'s judge-payload builder (currently
  `figure_filenames(discover_figures(config.course, config.number))`) is extended
  the same way so the persisted `figures` field already includes retrieved-item
  figures, keeping replay self-contained.

### 6. Tests (`utils/test_figures.py`)

- `lecture_*` and `practice_*` figures are discovered by
  `discover_figures_for_sources` from source labels.
- Backward-compat: `discover_figures(course, N)` still returns only
  `exercise_<N>_*` and ignores `lecture_*` / `practice_*` files.
- Source labels that don't name an item (`local:key_concepts`) yield no figures.
- De-duplication and stable ordering when several sources map to figures.

## Out of scope (YAGNI)

- Rendering the urban_transportation lecture slide PDFs into actual figure image
  files (separate content task).
- RAG-indexing the images themselves (`rag/sources.py` still excludes `figures/`;
  we index lecture *text* and attach sibling images on retrieval).
- The `figures.json` manifest (Approach C).

## Success criteria

- A `lecture_5_*.png` figure is sent to the tutor as vision content **only** on
  turns where a `lecture_5` chunk is retrieved, and never otherwise.
- Existing exercise-figure behavior is byte-for-byte unchanged across all callers.
- The judge grades against the same images the tutor saw.
- Tests cover exercise (regression), lecture, and practice discovery.
