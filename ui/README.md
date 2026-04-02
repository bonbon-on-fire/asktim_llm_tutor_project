# UI Module

Terminal runners for transcript generation and judge scoring with interactive CLI support.

## Available entrypoints

From repo root in PowerShell:

### 1) Generate raw transcripts (no judge)

**Interactive mode (default):**
```powershell
python -m ui.run_ui_raw
```

This will prompt you to select from numbered options:
- **Tutor prompts**: Available from `tutor/prompts/*.txt` (empty input = all)
- **Student personas**: Available from `students/personas/*.txt` (empty input = all)  
- **Course/exercise combinations**: Available from `curriculum/` (empty input = all)
- **Turn size**: Number of student+tutor exchanges per conversation
- **Trials**: Number of trials per configuration

**Command-line mode:**
```powershell
python -m ui.run_ui_raw --tutor tutor_03 --personas clueless_01 chaotic_02 --course philosophy --exercise 01 --turn-size 10 --trials 2
```

Run matrix: `tutor_prompts x student_personas x course_exercises x trials`

**Features:**
- Parallel processing (6 workers by default)
- Thread-safe transcript filename allocation (`transcript_XXXX.json`) during concurrent writes
- Automatic API key validation
- Interactive confirmation before processing

### 2) Judge raw transcripts (GPT or Claude)

**Interactive mode (default):**
```powershell
python -m ui.run_ui_judge
```

This will prompt you to select from numbered options:
- **Judge provider**: gpt or claude (required)
- **Judge prompt**: Available from `judge/prompts/judge_*.txt` (required)
- **Judge rubric**: Available from `judge/rubrics/rubric_*.md` (required)

**Command-line mode:**
```powershell
# Grade with GPT
python -m ui.run_ui_judge --provider gpt --prompt judge_05 --rubric rubric_05

# Grade with Claude  
python -m ui.run_ui_judge --provider claude --prompt judge_06 --rubric rubric_06
```

The script automatically discovers all raw transcripts in `*_raw` folders, copies each to the provider-specific folder (`*_gpt` or `*_claude`), then applies judging in-place on the copied file.

**Features:**
- Parallel processing (6 workers by default)
- Progress tracking with section scores
- Automatic API key validation per provider
- Overwrites existing graded files with warning
- Interactive confirmation before processing

### 3) Judge bundle files (GPT or Claude)

**Interactive mode (default):**
```powershell
python -m ui.run_ui_bundle_judge
```

This will prompt you to select from numbered options:
- **Judge provider**: gpt or claude (required)
- **Bundle type**: Available from `transcripts/bundles/bundles_raw/bundle_*/` (required)
- **Judge prompt**: Available from `judge/prompts/judge_*.txt` (required)
- **Judge rubric**: Available from `judge/rubrics/rubric_*.md` (required)

**Command-line mode:**
```powershell
# Grade bundle files with GPT
python -m ui.run_ui_bundle_judge --provider gpt --bundle-type 01 --prompt judge_05 --rubric rubric_05

# Grade bundle files with Claude
python -m ui.run_ui_bundle_judge --provider claude --bundle-type 02 --prompt judge_06 --rubric rubric_06
```

The script processes bundle files from `transcripts/bundles/bundles_raw/bundle_XX/` and writes results to `transcripts/bundles/bundles_{provider}/bundle_XX/`.

**Features:**
- Parallel processing (6 workers by default)
- Automatic API key validation per provider
- Interactive confirmation before processing

## Output paths

### Raw-only runs (`ui.run_ui_raw`)

Raw transcripts are saved to persona-specific raw folders:

- `transcripts/chaotic/chaotic_raw/`
- `transcripts/cooperative/cooperative_raw/`
- `transcripts/clueless/clueless_raw/`

Each file is auto-named as `transcript_XXXX.json`.

### Judged runs (`ui.run_ui_judge`)

Judged transcripts are saved to provider-specific folders:

**GPT judged:**
- `transcripts/chaotic/chaotic_gpt/`
- `transcripts/cooperative/cooperative_gpt/`
- `transcripts/clueless/clueless_gpt/`

**Claude judged:**
- `transcripts/chaotic/chaotic_claude/`
- `transcripts/cooperative/cooperative_claude/`
- `transcripts/clueless/clueless_claude/`

Each output file uses the same stem as raw input: `transcript_XXXX.json`

### Bundle judged runs (`ui.run_ui_bundle_judge`)

Bundle results are saved to provider-specific folders:

**GPT bundle judged:**
- `transcripts/bundles/bundles_gpt/bundle_XX/`

**Claude bundle judged:**
- `transcripts/bundles/bundles_claude/bundle_XX/`

Each output file converts from `bundle_XX.txt` to `bundle_XX.json`

## Transcript schema (core fields)

All transcript flows include run metadata and exchanges:

```json
{
  "tutor_prompt": "tutor_03",
  "student_persona": "chaotic_01",
  "course": "philosophy",
  "exercise_number": "01",
  "turn_size": 10,
  "context": "Course-level context loaded from curriculum/<course>/course.txt",
  "exercise": "Combined assignment text (course context + exercise + run configuration)...",
  "turns": 10,
  "exchanges": [
    {
      "turn": 1,
      "student": "...",
      "tutor": "...",
      "pedagogical_reasoning": "Tutor reasoning for this turn"
    }
  ]
}
```

Judged transcripts additionally include:

- `judge_prompt`
- `judge_rubric`
- `grade`

## Interactive CLI Features

All UI scripts support both interactive and command-line modes:

- **Interactive mode**: Run without arguments to get numbered selection prompts
- **Command-line mode**: Provide all required arguments to skip prompts
- **Smart defaults**: `run_ui_raw` allows empty input (defaults to "all available")
- **Required inputs**: Judge scripts require explicit selection of all options
- **Confirmation**: Interactive mode shows summary and asks for confirmation
- **Range support**: Select multiple items with ranges like `1-5` or `1,3,5-7`

## Parallelism configuration

- `ui.run_ui_raw`, `ui.run_ui_judge`, and `ui.run_ui_bundle_judge` all run with `6` workers by default.
- Adjust `PARALLEL_WORKERS` at the top of each runner file to change concurrency.

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `OPENAI_API_KEY` | Yes | OpenAI API key. Fails immediately if not set. |
| `OPENAI_MODEL` | No | Model name (default: `gpt-5.4`). |
| `ANTHROPIC_API_KEY` | For Claude judge | Anthropic API key required when using Claude provider. |
| `ANTHROPIC_MODEL` | No | Model name for Claude judge (default: `claude-sonnet-4-6`). |
