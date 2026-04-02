# Judge

LLM-based grader that scores tutor–student conversation transcripts against a rubric.

Current defaults in code:
- prompt: `judge_05`
- rubric: `rubric_05`

## Structure

```text
judge/
  run_judge.py                 — unified single-transcript judge core (provider: gpt|claude)
  run_judge_bundle.py           — unified bundle judge core (provider: gpt|claude)
  README.md
  prompts/
    judge_01.txt           — baseline prompt template
    judge_02.txt           — structured prompt template
    judge_03.txt           — prior prompt template (context + exercise aware)
    judge_04.txt           — current prompt template (context + exercise aware)
    judge_05.txt           — current prompt template (rubric_05 compatible)
    judge_06.txt           — latest prompt template
  rubrics/
    rubric_01.md           — original rubric profile
    rubric_02.md           — intermediate rubric profile
    rubric_03.md           — prior rubric profile (33 base + 9 bonus = 42 max)
    rubric_04.md           — prior rubric profile (47 base with section malus deductions)
    rubric_05.md           — current rubric profile (46 base points, no malus)
    rubric_06.md           — latest rubric profile
```

Transcripts live in the top-level `transcripts/` folder (not inside `judge/`).

## How it works

1. Load prompt from `prompts/<prompt_name>.txt`.
2. Inject rubric text from `rubrics/<rubric_name>.md` and the expected output schema.
3. Read transcript JSON from `transcripts/<relative_stem>.json`.
4. Call model, parse JSON output, normalize explanation fields, sanitize numeric fields, and validate schema.
5. If validation fails, retry with repair prompting (up to 3 total attempts).
6. Write `grade` back into the transcript file.

## Usage

### Single Transcript Judging

```python
from judge.run_judge import judge_transcript

result = judge_transcript("chaotic/chaotic_gpt/transcript_01")
print(result.total_score, result.max_score)  # e.g. 41, 46
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
in `ui/`:

```powershell
# GPT judge — grades all *_raw/ transcripts into *_gpt/ folders
python -m ui.run_ui_judge --provider gpt

# Claude judge — grades all *_raw/ transcripts into *_claude/ folders
python -m ui.run_ui_judge --provider claude
```

Both commands accept `--prompt` and `--rubric` flags to select versions:

```powershell
python -m ui.run_ui_judge --provider gpt --prompt judge_06 --rubric rubric_06
python -m ui.run_ui_judge --provider claude --prompt judge_06 --rubric rubric_06
```

Parallelism is controlled by the `PARALLEL_WORKERS` constant at the top of
each runner file (default: 6).

### Bundle Judging (combined multi-transcript bundles)

Grade transcript bundles where multiple transcripts are combined into one
prompt for holistic/comparative evaluation:

```python
from judge.run_judge_bundle import judge_transcript_bundle

result = judge_transcript_bundle(
    "transcripts/bundles/bundles_raw/bundle_01/bundle_001.txt",
    provider="gpt",
    prompt_name="judge_05",
    rubric_name="rubric_05",
    output_path="transcripts/bundles/bundles_gpt/bundle_01/bundle_001.json",
)
print(result.total_score, result.max_score)
```

To grade all bundles of a given type, use the bundle UI runner:

```powershell
# GPT — grade all bundle_01 bundles
python -m ui.run_ui_bundle_judge --provider gpt --bundle-type 01

# Claude — grade all bundle_02 bundles
python -m ui.run_ui_bundle_judge --provider claude --bundle-type 02 --prompt judge_06 --rubric rubric_06
```

Bundle files live in `transcripts/bundles/bundles_raw/bundle_XX/` and output
goes to `transcripts/bundles/bundles_gpt/bundle_XX/` (or `bundles_claude/`).
Each bundle file lists 3 transcript paths; they are combined into a single
prompt with full metadata headers and graded holistically.

## Rubric summary

For `rubric_05` (current):
- `1. Pedagogy` (`1.1`-`1.3`): `24` max points
- `2. Dialogue quality` (`2.1`-`2.2`): `12` max points
- `3. Communication quality` (`3.1`-`3.2`): `10` max points
- `Base total`: `46` max points

**Note**: `rubric_05` removed malus deductions. Total score equals base score.

Maximum total score: **46**.

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
