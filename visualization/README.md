# Visualization

Two modules, different questions:

- **`run_visualization`** — one tutor's rubric profile in depth (11 charts).
  Reads `transcripts/<type>/<type>_judge/`.
- **`run_comparison_viz`** — AskTIM vs STEM AskTIM, 5 charts. Reads the
  comparison folders `transcripts/<type>/<type>_{cmp,phys}_{asktim,stem}/`.
  See [Comparison charts](#comparison-charts) below.

`run_visualization` has no notion of two arms — every chart groups by persona
only, so pointed at the comparison corpus it would silently average the two
tutors into the same bar. Use `run_comparison_viz` for anything two-armed.

Generate Claude transcript grading charts. Each run produces **all 11** configured
outputs (no prompts or modes): the six persona-type evaluation charts
(`01`–`06`) followed by the score-distribution and per-transcript grade charts
(`07`–`11`).

## Inputs

**Claude machine grades** — judged transcript JSON files:

- `transcripts/<persona_type>/<persona_type>_judge/transcript_*.json` — judged (graded) transcripts

Paths follow the current repo layout: one folder per persona family (`chaotic`, `cooperative`, `clueless`) with graded subfolders.

## Run

Install dependencies from the repo root, then run:

```powershell
pip install -r requirements.txt
python -m visualization.run_visualization
```

This generates all 11 charts, including the persona-type evaluation charts
(`01`–`06`, bar/heatmap/boxplot by persona and problem).

## Outputs

All 11 charts are written to `visualization/outputs/`, numbered with a
zero-padded `##_` prefix:

| File | Description |
| ---- | ----------- |
| `10_grades_clueless_transcripts.png` | Same chart restricted to clueless persona. |
| `11_grades_cooperative_transcripts.png` | Same chart restricted to cooperative persona. |

All charts are built from one shared `GradeRow` model, so transcripts are read
once per run and fed to both the persona-type (`01`–`06`) and line/histogram
(`07`–`11`) families. The per-transcript line charts annotate transcript count and
mean score with integer y-ticks.

## Sorting

Rows are ordered with the same key as other tooling: persona type, full student persona, course, exercise number, then transcript number.

## Comparison charts

```powershell
python -m visualization.run_comparison_viz
```

Writes four charts to `visualization/outputs/comparison/`:

| Chart | Shows |
| --- | --- |
| `01_score_by_course.png` | **Judge score by course** — mean of 27 conversations per tutor per course assignment (+4.5 SCD, +3.4 physics) |
| `02_score_by_persona.png` | **Judge score by student type** — the two are close on cooperative students and separate as students get harder |
| `03_integrity_cliff.png` | **Answer-giving failures** — conversations where the tutor handed over submission-ready work (the 12-point `1.1.A.a` deduction) |
| `04_cost_per_conversation.png` | **Tutor cost per conversation** — STEM AskTIM's per-turn assessment call broken out. Tutor-side model calls only; the simulated student is a harness artifact (in production the student is a person) |

**Scope:** reads only what is on disk — the SCD *practices* and *physics* rounds,
108 conversations (27 per arm per course). A third round (SCD exercises 1–3) was
run and deleted before being committed; it is deliberately not folded in, so
every number in these charts is recomputable from the repo.

Every chart uses the same frame — concise title, one caption line, legend centred at the bottom — so the set reads as one deck.

Each run also writes **bare** copies (no title, no caption, legend only) to `visualization/outputs/comparison/bare/`. Those are what [`docs/meeting_deck_2026_july.md`](../docs/meeting_deck_2026_july.md) embeds — the heading and explanation live in the markdown, so the words exist in one place and can't drift from the image.

Series colours are the validated two-slot categorical pair (all-pairs CVD ΔE
24.7, normal-vision 33.6, both ≥ 3:1 on the light surface). Every bar is also
direct-labelled, so identity never rests on hue alone.
