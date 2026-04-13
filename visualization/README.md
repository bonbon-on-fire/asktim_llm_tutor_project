# Visualization

Generate score comparison charts for GPT vs Claude transcript grading.

## Inputs

Reads judged transcript JSON files from:

- `transcripts/<persona_type>/<persona_type>_gpt/transcript_*.json`
- `transcripts/<persona_type>/<persona_type>_claude/transcript_*.json`
- `judge/hand_grade_workbook.xlsx` (sheet: `compiled grading`, rows where `grader name = faizan`)

## Run

```powershell
python -m visualization.run_visualization
```

## Outputs

Written to `visualization/outputs/`:

| # | File | Description |
| - | ---- | ----------- |
| 1 | `section_discrepancy_by_rubric_section_gpt_vs_claude.png` | Bar chart of per-section grading discrepancies on paired transcripts (mean absolute difference), with `n` and signed mean delta annotations. |
| 2 | `subsection_discrepancy_by_subsection_gpt_vs_claude.png` | Subsection (`X.X`) discrepancy chart for regular graded transcripts, with `n` and signed mean delta annotations. |
| 3 | `individual_grades_all_transcripts_gpt_vs_claude.png` | Single line chart of total scores per individual transcript across all personas and versions. |
| 4 | `subsection_correlation_heatmap_all_providers_all_personas_normalized.png` | Joined subsection-pair Pearson correlation heatmap on normalized subsection scores (`score / max`) across GPT + Claude combined; title and axis labels include `n` counts. |
| 5 | `subsection_correlation_heatmap_gpt_all_personas_normalized.png` | Subsection-pair Pearson correlation heatmap on normalized subsection scores (`score / max`) for GPT across all personas; title and axis labels include `n` counts. |
| 6 | `subsection_correlation_heatmap_claude_all_personas_normalized.png` | Subsection-pair Pearson correlation heatmap on normalized subsection scores (`score / max`) for Claude across all personas; title and axis labels include `n` counts. |
| 7 | `hand_grades_faizan_vs_gpt_vs_claude.png` | Exact-transcript comparison chart for Faizan hand grades vs GPT and Claude, with Pearson/Spearman correlations. |
| 8 | `hand_grades_faizan_vs_claude_subsection_heatmap_xxx.png` | Heatmap of subsection (`X.X.X`) deduction correlation between Faizan hand grading and regular Claude grading on exact transcript matches. |

All charts include Pearson r, Spearman rho, and mean scores.

## Alignment

Individual transcripts are matched across providers by composite key:
`student_persona | course | exercise_number | transcript_name`.

Missing rows in either provider appear as gaps (NaN) in the line charts.
