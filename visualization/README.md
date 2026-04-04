# Visualization

Generate score comparison charts for GPT vs Claude transcript grading.

## Inputs

Reads judged transcript JSON files from:

- `transcripts/<persona_type>/<persona_type>_gpt/transcript_*.json`
- `transcripts/<persona_type>/<persona_type>_claude/transcript_*.json`
- `transcripts/<persona_type>/<persona_type>_gpt_v2/transcript_*.json`
- `transcripts/<persona_type>/<persona_type>_claude_v2/transcript_*.json`
- `transcripts/<persona_type>/<persona_type>_gpt_v3/transcript_*.json`
- `transcripts/<persona_type>/<persona_type>_claude_v3/transcript_*.json`
- `transcripts/bundles/bundles_gpt/bundle_01/bundle_*.json`
- `transcripts/bundles/bundles_claude/bundle_01/bundle_*.json`
- `transcripts/bundles/bundles_gpt_v2/bundle_01/bundle_*.json`
- `transcripts/bundles/bundles_claude_v2/bundle_01/bundle_*.json`
- `transcripts/bundles/bundles_gpt_v3/bundle_01/bundle_*.json`
- `transcripts/bundles/bundles_claude_v3/bundle_01/bundle_*.json`

Individual transcript grading is generated as one combined chart across all transcripts.
Bundle Type 01 charts are also generated separately for each persona family.

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
| 7 | `bundle_01_grades_chaotic_gpt_vs_claude.png` | Bundle Type 01 line chart for chaotic bundles only. |
| 8 | `bundle_01_grades_cooperative_gpt_vs_claude.png` | Bundle Type 01 line chart for cooperative bundles only. |
| 9 | `bundle_01_grades_clueless_gpt_vs_claude.png` | Bundle Type 01 line chart for clueless bundles only. |
| 10 | `section_discrepancy_by_rubric_section_gpt_vs_claude_v2.png` | Same as #1, but computed only from `_v2` graded transcripts. |
| 11 | `subsection_discrepancy_by_subsection_gpt_vs_claude_v2.png` | Same as #2, but computed only from `_v2` graded transcripts. |
| 12 | `individual_grades_all_transcripts_gpt_vs_claude_v2.png` | Same as #3, but computed only from `_v2` graded transcripts. |
| 13 | `subsection_correlation_heatmap_all_providers_all_personas_normalized_v2.png` | Same as #4, but computed only from `_v2` graded transcripts. |
| 14 | `subsection_correlation_heatmap_gpt_all_personas_normalized_v2.png` | Same as #5, but computed only from `_v2` graded transcripts. |
| 15 | `subsection_correlation_heatmap_claude_all_personas_normalized_v2.png` | Same as #6, but computed only from `_v2` graded transcripts. |
| 16 | `bundle_01_grades_chaotic_gpt_vs_claude_v2.png` | Same as #7, but computed only from `_v2` graded bundles. |
| 17 | `bundle_01_grades_cooperative_gpt_vs_claude_v2.png` | Same as #8, but computed only from `_v2` graded bundles. |
| 18 | `bundle_01_grades_clueless_gpt_vs_claude_v2.png` | Same as #9, but computed only from `_v2` graded bundles. |
| 19 | `section_discrepancy_by_rubric_section_gpt_vs_claude_v3.png` | Same as #1, but computed only from `_v3` graded transcripts. |
| 20 | `subsection_discrepancy_by_subsection_gpt_vs_claude_v3.png` | Same as #2, but computed only from `_v3` graded transcripts. |
| 21 | `individual_grades_all_transcripts_gpt_vs_claude_v3.png` | Same as #3, but computed only from `_v3` graded transcripts. |
| 22 | `subsection_correlation_heatmap_all_providers_all_personas_normalized_v3.png` | Same as #4, but computed only from `_v3` graded transcripts. |
| 23 | `subsection_correlation_heatmap_gpt_all_personas_normalized_v3.png` | Same as #5, but computed only from `_v3` graded transcripts. |
| 24 | `subsection_correlation_heatmap_claude_all_personas_normalized_v3.png` | Same as #6, but computed only from `_v3` graded transcripts. |
| 25 | `bundle_01_grades_chaotic_gpt_vs_claude_v3.png` | Same as #7, but computed only from `_v3` graded bundles. |
| 26 | `bundle_01_grades_cooperative_gpt_vs_claude_v3.png` | Same as #8, but computed only from `_v3` graded bundles. |
| 27 | `bundle_01_grades_clueless_gpt_vs_claude_v3.png` | Same as #9, but computed only from `_v3` graded bundles. |
| 28 | `individual_grades_gpt_regular_vs_v3.png` | Per-transcript line chart comparing regular GPT grades versus `_v3` GPT grades. |
| 29 | `individual_grades_claude_regular_vs_v3.png` | Per-transcript line chart comparing regular Claude grades versus `_v3` Claude grades. |

All charts include Pearson r, Spearman rho, and mean scores.

## Alignment

Individual transcripts are matched across providers by composite key:
`student_persona | course | exercise_number | transcript_name`.

Bundle files are matched by filename (e.g. `bundle_001`).

Missing rows in either provider appear as gaps (NaN) in the line charts.
