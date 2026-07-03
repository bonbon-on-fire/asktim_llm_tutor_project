# internal_testing

Internal runners for testing the tutor: bulk transcript generation and judge scoring, with interactive CLI support. (Renamed from `internal_ui/` — earlier `ui/` — since these are CLI test runners, not a web UI.)

## Files

```text
internal_testing/
  run_transcript.py             — generate raw transcripts in bulk (interactive or CLI)
  run_transcript_rag.py         — batch runner for RAG-context tutor simulations (SC2x exercises + practice problems)
  run_transcript_judge.py           — grade transcripts with the GPT or Claude judge
  cli_utils.py              — shared interactive numbered-selection prompt helpers
```

## Available entrypoints

From repo root in PowerShell:

### 1) Generate raw transcripts (no judge)

**Interactive mode (default):**
```powershell
python -m internal_testing.run_transcript
```

This will prompt you to select from numbered options:
- **Tutor provider**: `gpt` or `claude` (required)
- **Tutor prompts**: Available from `tutor/prompts/*.txt` (empty input = all)
- **Student personas**: Available from `students/personas/*.txt` (empty input = all)
- **Course/exercise combinations**: Available from `curriculum/<course>/exercises/` (empty input = all)
- **Turn size**: Number of student+tutor exchanges per conversation
- **Trials**: Number of trials per configuration

Exercise prompts are read from `curriculum/<course>/exercises/exercise_<NN>.txt` (path resolution centralized in [`utils/curriculum.py`](../utils/curriculum.py)). Any figures under `curriculum/<course>/figures/` matching the exercise are auto-discovered, passed to both tutor and student as multimodal input, and recorded in the transcript's `figures` field. Per-course lecture transcripts under `curriculum/<course>/lectures/` are folded into the assignment context.

**Command-line mode:**
```powershell
# Generate with GPT tutor (default output: *_raw/)
python -m internal_testing.run_transcript --provider gpt --tutor tutor_03 --personas clueless chaotic --course cities_and_climate_change --exercise 01 --turn-size 10 --trials 2

# Generate with Claude tutor
python -m internal_testing.run_transcript --provider claude --tutor tutor_05 --personas clueless --course cities_and_climate_change --exercise 01 --turn-size 10 --trials 2

# Custom output folder: writes to *_raw_tutor_05/ instead of *_raw/ (--yes skips confirmation)
python -m internal_testing.run_transcript --provider claude --tutor tutor_05 --personas chaotic --course cities_and_climate_change --exercise 01 --turn-size 10 --trials 10 --output-suffix raw_tutor_05 --yes
```

Run matrix: `tutor_prompts x student_personas x course_exercises x trials`

**Features:**
- Parallel processing (6 workers by default)
- Thread-safe transcript filename allocation (`transcript_NN.json`) during concurrent writes
- Automatic API key validation
- Interactive confirmation before processing

### 2) Judge raw transcripts (GPT or Claude)

**Interactive mode (default):**
```powershell
python -m internal_testing.run_transcript_judge
```

This will prompt you to select from numbered options:
- **Judge provider**: gpt or claude (required)
- **Judge prompt**: Available from `judge/prompts/judge_*.txt` (required)
- **Judge rubric**: Available from `judge/rubrics/rubric_*.md` (required)

**Command-line mode:**
```powershell
# Grade with GPT (reads *_raw/, writes *_gpt/)
python -m internal_testing.run_transcript_judge --provider gpt --prompt judge_08 --rubric rubric_08

# Grade with Claude (reads *_raw/, writes *_claude/)
python -m internal_testing.run_transcript_judge --provider claude --prompt judge_08 --rubric rubric_08

# Read from *_raw_tutor_05/, write to *_claude_tutor_05/ (--yes skips confirmation)
python -m internal_testing.run_transcript_judge --provider claude --prompt judge_08 --rubric rubric_08 \
  --source-suffix raw_tutor_05 --output-suffix tutor_05 --yes
```

The script discovers all transcripts matching `*_{source-suffix}/transcript_*.json`, copies each to the provider+suffix-specific folder, then applies judging in-place.

**Features:**
- Parallel processing (6 workers by default)
- Progress tracking with section scores
- Automatic API key validation per provider
- Overwrites existing graded files with warning
- Interactive confirmation before processing

## Output paths

### Raw-only runs (`internal_testing.run_transcript`)

Raw transcripts are saved to persona-specific raw folders:

- `transcripts/chaotic/chaotic_raw/`
- `transcripts/clueless/clueless_raw/`
- `transcripts/cooperative/cooperative_raw/`

With `--output-suffix raw_tutor_05`, output goes to `*_raw_tutor_05/` instead:

- `transcripts/chaotic/chaotic_raw_tutor_05/`
- `transcripts/clueless/clueless_raw_tutor_05/`
- `transcripts/cooperative/cooperative_raw_tutor_05/`

Each file is auto-named as `transcript_NN.json`.

### Judged runs (`internal_testing.run_transcript_judge`)

Judged transcripts are saved to provider-specific folders:

**GPT judged:**
- `transcripts/chaotic/chaotic_gpt/`
- `transcripts/clueless/clueless_gpt/`
- `transcripts/cooperative/cooperative_gpt/`

**Claude judged (default):**
- `transcripts/chaotic/chaotic_claude/`
- `transcripts/clueless/clueless_claude/`
- `transcripts/cooperative/cooperative_claude/`

**Claude judged with custom suffix** (`--source-suffix raw_tutor_05 --output-suffix tutor_05`):
- `transcripts/chaotic/chaotic_claude_tutor_05/`
- `transcripts/clueless/clueless_claude_tutor_05/`
- `transcripts/cooperative/cooperative_claude_tutor_05/`

Each output file uses the same stem as the source input: `transcript_NN.json`

## Transcript schema (core fields)

All transcript flows include run metadata and exchanges:

```json
{
  "tutor_provider": "gpt",
  "tutor_prompt": "tutor_03",
  "student_persona": "chaotic",
  "course": "cities_and_climate_change",
  "exercise_number": "01",
  "figures": ["exercise_08_spider_diagram.png"],
  "turn_size": 10,
  "context": "Course-level context loaded from curriculum/<course>/course.txt (+ syllabus + lecture transcripts when present)",
  "exercise": "Combined assignment text (course context + syllabus + lecture transcripts + exercise + run configuration)...",
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

`run_transcript` and `run_transcript_judge` support both interactive and command-line modes.

- **Interactive mode**: Run without arguments to get numbered selection prompts
- **Command-line mode**: Provide all required arguments to skip prompts
- **Smart defaults**: `run_transcript` allows empty input (defaults to "all available")
- **Required inputs**: Judge scripts require explicit selection of all options
- **Confirmation**: Interactive mode shows summary and asks for confirmation
- **Range support**: Select multiple items with ranges like `1-5` or `1,3,5-7`

## Parallelism configuration

- `internal_testing.run_transcript` and `internal_testing.run_transcript_judge` both run with `6` workers by default.
- Adjust `PARALLEL_WORKERS` at the top of each runner file to change concurrency.

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `OPENAI_API_KEY` | For GPT | OpenAI API key. Required when using GPT as tutor or judge provider. |
| `OPENAI_MODEL` | No | OpenAI model name (default: `gpt-5.4`). |
| `ANTHROPIC_API_KEY` | For Claude | Anthropic API key. Required when using Claude as tutor or judge provider. |
| `ANTHROPIC_MODEL` | No | Anthropic model name for Claude tutor or judge (default: `claude-sonnet-4-6`). |
