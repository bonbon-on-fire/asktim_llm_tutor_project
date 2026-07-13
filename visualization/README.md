# Visualization

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
| `01_total_by_persona_type.png` | Mean total score by persona type, with spread. |
| `02_sections_by_persona_type.png` | Rubric-section attainment (% of max) by persona type. |
| `03_exercise_vs_practice.png` | Exercise vs practice attainment by persona type. |
| `04_score_distribution.png` | Total-score distribution by persona type (boxplot). |
| `05_heatmap_type_x_section.png` | Heatmap: persona type × rubric section (% of max). |
| `06_by_problem.png` | Mean attainment by problem (exercise/practice 01–03). |
| `07_score_histogram_all.png` | **Histogram** of Claude total scores across all graded transcripts, with mean line and the "answer-giving penalty zone" (≤ max−12) shaded. Annotates n, mean, median, % perfect, and % in the penalty zone. |
| `08_grades_all_transcripts.png` | Line chart of Claude **total score** per transcript, all personas combined. |
| `09_grades_chaotic_transcripts.png` | Same chart restricted to chaotic persona. |
| `10_grades_clueless_transcripts.png` | Same chart restricted to clueless persona. |
| `11_grades_cooperative_transcripts.png` | Same chart restricted to cooperative persona. |

All charts are built from one shared `GradeRow` model, so transcripts are read
once per run and fed to both the persona-type (`01`–`06`) and line/histogram
(`07`–`11`) families. The per-transcript line charts annotate transcript count and
mean score with integer y-ticks.

## Sorting

Rows are ordered with the same key as other tooling: persona type, full student persona, course, exercise number, then transcript number.
