# Visualization

Generate Claude transcript grading charts. Each run produces **all** configured outputs (no prompts or modes).

## Inputs

**Claude machine grades** — judged transcript JSON files:

- `transcripts/<persona_type>/<persona_type>_claude/transcript_*.json` — standard Claude grades
- `transcripts/<persona_type>/<persona_type>_claude_mini/transcript_*.json` — Claude grades on mini-continuation transcripts (chaotic + clueless only)
- `transcripts/<persona_type>/<persona_type>_claude_tutor_05/transcript_*.json` — Claude grades on tutor_05-generated transcripts

Paths follow the current repo layout: one folder per persona family (`chaotic`, `cooperative`, `clueless`) with graded subfolders.

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

| File | Description |
| ---- | ----------- |
| `claude_score_histogram_all.png` | **Histogram** of Claude total scores across all graded transcripts, with mean line and the "answer-giving penalty zone" (≤ max−12) shaded. Annotates n, mean, median, % perfect, and % in the penalty zone. |
| `claude_mean_score_by_course.png` | **Bar chart** of mean Claude total score **per course** (± standard deviation, with n labels), sorted by mean. Shows how consistently the tutor scores across subjects. Only courses with graded transcripts appear. |
| `claude_grades_all_transcripts.png` | Line chart of Claude **total score** per transcript, all personas combined (standard pipeline). |
| `claude_grades_chaotic_transcripts.png` | Same chart restricted to chaotic persona. |
| `claude_grades_clueless_transcripts.png` | Same chart restricted to clueless persona. |
| `claude_grades_cooperative_transcripts.png` | Same chart restricted to cooperative persona. |
| `claude_tutor_05_grades_chaotic.png` | Bar chart of Claude scores on tutor_05-generated transcripts, chaotic persona. |
| `claude_tutor_05_grades_clueless.png` | Same, clueless persona. |
| `claude_tutor_05_grades_cooperative.png` | Same, cooperative persona. |
| `original_vs_mini_claude_chaotic.png` | Grouped bar chart comparing original (tutor_04, Claude) vs mini (tutor_05, Claude) grades per transcript, chaotic persona. Shows mean score delta. |
| `original_vs_mini_claude_clueless.png` | Same, clueless persona. |
| `hand_grades_faizan_vs_claude.png` | Hand (Faizan) vs Claude total score on matched transcripts; annotation includes Pearson and Spearman correlation and means. |
| `hand_grades_romain_vs_claude.png` | Same for Romain. |
| `hand_grades_nishita_vs_claude.png` | Same for Nishita. |

If a grader sheet is missing or has no overlapping keys with Claude data, that chart is skipped with a console message.

Annotation box shows transcript count and mean score. Y-axis uses integer ticks.

## Sorting

Rows are ordered with the same key as other tooling: persona type, full student persona, course, exercise number, then transcript number.
