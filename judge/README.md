# Judge

LLM-based grader that scores tutor–student conversation transcripts against a rubric.

## Structure

```
judge/
  __init__.py          — package exports
  run_judge.py         — LangGraph engine, validation, scoring logic
  README.md
  prompts/
    judge_01.txt       — judge system prompt template (references rubric + schema)
  rubrics/
    rubric_01.md       — grading rubric (deduction-based, 33 base + 12 bonus = 45 max)
```

Transcripts live in the top-level `transcripts/` folder (not inside `judge/`).

## How it works

1. Loads the judge system prompt from `prompts/judge_01.txt`, injecting the rubric text from `rubrics/rubric_01.md` and the expected JSON schema.
2. Reads a transcript JSON from `transcripts/<name>.json`.
3. Formats the conversation and sends it to the LLM with the system prompt.
4. Parses the LLM's JSON response, sanitizes numeric values, and validates against the schema.
5. If validation fails, sends a repair prompt and retries once (up to 2 attempts total).
6. Writes a `grade` object back into the transcript JSON file.

## Usage

```python
from judge import judge_transcript

result = judge_transcript("chaotic_01_exercise_01_01")
print(result.total_score, result.max_score)  # e.g. 38.5, 45.0
```

You can also choose specific judge prompt + rubric versions:

```python
result = judge_transcript(
    "chaotic/transcript_01",
    prompt_name="judge_01",
    rubric_name="rubric_01",
)
```

## Rubric summary

| Section                  | Sub-criteria | Max points | Bonus |
| :----------------------- | :----------: | ---------: | ----: |
| 1. Pedagogy              |    1.1–1.3   |         11 |     4 |
| 2. Dialogue quality      |    2.1–2.3   |         11 |     4 |
| 3. Communication quality |    3.1–3.3   |         11 |     4 |
| **Total**                |              |     **33** |**12** |

Maximum total score (with bonus): **45**.

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `OPENAI_API_KEY` | Yes | OpenAI API key. Fails immediately if not set. |
| `OPENAI_MODEL` | No | Model name (default: `gpt-5.2`). |
