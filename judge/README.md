# Judge

LLM-based grader that scores tutor–student conversation transcripts against a rubric.

Current defaults in code (`judge/run_judge.py`):
- prompt: `judge_05`
- rubric: `rubric_05`

**Latest / recommended:** `judge_08` + `rubric_08` (40-point base, see [Rubric summary](#rubric-summary)). This is what recent runs grade with — pass `--prompt judge_08 --rubric rubric_08` (the in-code defaults above haven't been bumped). The Claude judge (`provider="claude"`) is the primary grader; GPT judging was paused (lower self-consistency).

## Structure

```text
judge/
  run_judge.py                       — unified single-transcript judge core (provider: gpt|claude)
  hand_grade_workbook.xlsx           — manual grading workbook for judge calibration
  hand_grade_workbook_build.py       — build workbook from stratified sample + run Claude fill
  hand_grade_workbook_claude_fill.py — fill compiled `claude` rows from *_claude transcript grades
  rebuild_hand_grade_workbook.py     — regenerate the hand-grade workbook in place
  claude_transcript_scores.tsv       — exported Claude per-transcript scores (calibration aid)
  README.md
  prompts/
    judge_01.txt           — baseline prompt template
    judge_02.txt           — structured prompt template
    judge_03.txt           — prior prompt template (context + exercise aware)
    judge_04.txt           — prompt template (context + exercise aware)
    judge_05.txt           — prompt template (rubric_05 compatible)
    judge_06.txt           — prompt template
    judge_07.txt           — prompt template
    judge_08.txt           — latest prompt template
  rubrics/
    rubric_01.md           — original rubric profile
    rubric_02.md           — intermediate rubric profile
    rubric_03.md           — prior rubric profile (33 base + 9 bonus = 42 max)
    rubric_04.md           — prior rubric profile (47 base with section malus deductions)
    rubric_05.md           — rubric profile (46 base points, no malus)
    rubric_06.md           — rubric profile
    rubric_07.md           — rubric profile
    rubric_08.md           — latest rubric profile
```

Transcripts live in the top-level `transcripts/` folder (not inside `judge/`).

## Manual grading workbook

`judge/hand_grade_workbook.xlsx` is structured for rubric-level deduction entry with 4 sheets:
- `compiled grading`
- `faizan grading`
- `romain grading`
- `nishita grading`

`faizan grading` / `romain grading` / `nishita grading` include a `transcript` column after `transcript number` (plain text per turn, same field order as raw JSON: `turn`, `student`, `tutor`, `pedagogical_reasoning`, labeled `turn:` / `student:` / `tutor:` / `pedagological reasoning:`).
Deduction columns follow `rubric_08` subsections (excluding `1.3.C`).
`total score` is computed as `40 - SUM(deductions)` per row (rubric_08 base total).
In `compiled grading`, rows for `faizan`/`romain`/`nishita` auto-pull deduction values from the corresponding grader sheet via key-based lookup formulas. `claude` rows can be filled from existing `*_claude` transcript grades with `python judge/hand_grade_workbook_claude_fill.py` (subsection deductions derived from each grade’s `sub_criterion_id` / `points` fields). To rebuild the stratified 20-transcript workbook from scratch and run that fill step, use `python judge/hand_grade_workbook_build.py`.

## How it works

1. Load prompt from `prompts/<prompt_name>.txt`.
2. Inject rubric text from `rubrics/<rubric_name>.md` and the expected output schema.
3. Read transcript JSON from `transcripts/<relative_stem>.json`.
4. If the transcript has a `figures` field (filenames of curriculum images), re-resolve those names to paths under `curriculum/<course>/figures/` via [`utils.figures.resolve_figure_filenames`](../utils/figures.py) and attach the images to the grading prompt — so the judge grades against the same figure the tutor saw. Empty/absent `figures` = text-only grading (unchanged).
5. Call model, parse JSON output, normalize explanation fields, sanitize numeric fields, and validate schema.
6. If validation fails, retry with repair prompting (up to 3 total attempts).
7. Write `grade` back into the transcript file.

## Usage

### Single Transcript Judging

```python
from judge.run_judge import judge_transcript

result = judge_transcript("chaotic/chaotic_gpt/transcript_01")
print(result.total_score, result.max_score)  # e.g. 37, 40 (rubric_08)
```

You can also choose specific judge prompt + rubric versions:

```python
result = judge_transcript(
    "chaotic/chaotic_gpt/transcript_01",
    provider="gpt",
    prompt_name="judge_06",
    rubric_name="rubric_06",
)
```

Claude example:

```python
from judge.run_judge import judge_transcript

result = judge_transcript("chaotic/chaotic_claude/transcript_01", provider="claude")
print(result.total_score, result.max_score)
```

### Judging All Transcripts Individually

Grade every raw transcript across all persona types using the judge runner
in `internal_ui/`:

```powershell
# GPT judge — grades all *_raw/ transcripts into *_gpt/ folders
python -m internal_ui.run_ui_judge --provider gpt

# Claude judge — grades all *_raw/ transcripts into *_claude/ folders
python -m internal_ui.run_ui_judge --provider claude
```

All flags:

```powershell
# --prompt and --rubric select versions; --yes skips confirmation prompt
python -m internal_ui.run_ui_judge --provider gpt --prompt judge_08 --rubric rubric_08 --yes

# --source-suffix reads from *_{suffix}/ instead of *_raw/
# --output-suffix independently overrides the target folder suffix
python -m internal_ui.run_ui_judge --provider claude --prompt judge_08 --rubric rubric_08 \
  --source-suffix raw_tutor_05 --output-suffix tutor_05 --yes
```

Parallelism is controlled by the `PARALLEL_WORKERS` constant at the top of
each runner file (default: 6).

## Rubric summary

For `rubric_08` (latest / recommended):
- `1. Pedagogy` (`1.1`-`1.3`): `20` max points — `1.1` Socratic / no direct work (12), `1.2` scaffolding (6), `1.3` meta-learning (2)
- `2. Dialogue quality` (`2.1`-`2.2`): `12` max points — `2.1` redundancy (4), `2.2` assignment anchoring (8)
- `3. Communication quality` (`3.1`-`3.2`): `8` max points — `3.1` bite-sized/clear (4), `3.2` tone & formative framing (4)
- `Base total`: `40` max points

**Deductions only** — each sub-criterion starts at full points and loses points on evidence. The single biggest penalty is all 12 points of `1.1` if the tutor produces near-submission-ready work (the core "never give the answer" guarantee).

Maximum total score: **40** (`rubric_08`). The earlier `rubric_05` was **46** (Pedagogy 24 / Dialogue 12 / Communication 10); both removed malus deductions, so total score equals base score.

## Output contract (current)

- Scores are whole integers only.
- Top-level key order ends with `total_score`, then `judge_llm_calls`.
- `overview` replaces `justifications` and appears near the end.
- `judge_reasoning` is included in each graded output as explicit scoring rationale.
- `judge_reasoning` normalization mirrors tutor-style fallback behavior:
  - if model provides `judge_reasoning`, keep it
  - else if `overview` exists, copy `overview` into `judge_reasoning`
  - else inject runtime fallback reasoning text
- `overview` is also guaranteed in output; if missing from model output, runtime fills a fallback overview.
- Deductions are ordered as `evidence_turns`, `sub_criterion_id`, `reason`, then `points` (`evidence_turns` optional).
- For `rubric_04`/`rubric_05`/`rubric_06`, each deduction must include an exact rubric sub-sub ID in `sub_criterion_id` (for example `1.1.A.a`, `2.2.D.a`, `3.2.C.b`).
- For `rubric_05`: No malus deductions. `total_score` equals `total_base_score`.
- Judge input supports both transcript `context` and `exercise`.

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `OPENAI_API_KEY` | For GPT judge | OpenAI API key. Fails immediately if not set. |
| `OPENAI_MODEL` | No | Model name (default: `gpt-5.4`). |
| `JUDGE_OPENAI_REASONING_EFFORT` | No | OpenAI reasoning effort for GPT judge: `low`, `medium`, `high`, or `off`. Default: `medium`. |
| `JUDGE_INCLUDE_TIMESTAMP` | No | If truthy (`1/true/yes/on`), include `timestamp_utc` in grade output. Default off for deterministic artifacts. |
| `ANTHROPIC_API_KEY` | For Claude judge | Anthropic API key required by Claude judge flow. |
| `ANTHROPIC_MODEL` | No | Model name for Claude judge (default: `claude-sonnet-4-6`). |

## Claude Judge Module

`judge/run_judge.py` handles both providers with `provider="gpt"|"claude"`:
- Same transcript input/output contract.
- Same schema validation, sanitization, and retry behavior.
- Uses `ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` (default: `claude-sonnet-4-6`).
