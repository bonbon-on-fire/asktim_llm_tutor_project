# Visualization

Generate Claude transcript grading charts. Each run produces **all** configured outputs (no prompts or modes).

## Inputs

**Claude machine grades** — judged transcript JSON files:

- `transcripts/<persona_type>/<persona_type>_claude/transcript_*.json`

Paths follow the current repo layout: one folder per persona family (`chaotic`, `cooperative`, `clueless`, …) with a `*_claude` graded subfolder.

**Hand grades (optional comparison charts)** — Excel workbook:

- `judge/hand_grade_workbook.xlsx` — sheets named `{grader} grading` (e.g. `faizan grading`) with columns `persona type`, `transcript number`, `total score`, and optionally `grader name`. Rows are matched to Claude rows by `(persona type, transcript number)`.

## Run

Install dependencies (including **openpyxl** for Excel hand grades) from the repo root, then run:

```powershell
pip install -r requirements.txt
python -m visualization.run_visualization
```

## Outputs

Written to `visualization/outputs/`:

| # | File | Description |
| - | ---- | ----------- |
| 1 | `claude_grades_all_transcripts.png` | Line chart of Claude **total score** per transcript, all personas combined (sorted by persona, course, exercise, transcript id). |
| 2+ | `claude_grades_<persona>_transcripts.png` | Same chart restricted to one persona family (e.g. `claude_grades_chaotic_transcripts.png`). One file per persona present in the data. |
| next | `hand_grades_faizan_vs_claude.png` | Hand (Faizan) vs Claude total score on matched transcripts; annotation includes Pearson and Spearman correlation and means. |
| next | `hand_grades_romain_vs_claude.png` | Same for Romain. |
| next | `hand_grades_nishita_vs_claude.png` | Same for Nishita. |

If a grader sheet is missing or has no overlapping keys with Claude data, that chart is skipped with a console message.

Annotation box shows transcript count and mean score. Y-axis uses integer ticks.

## Sorting

Rows are ordered with the same key as other tooling: persona type, full student persona, course, exercise number, then transcript number.
