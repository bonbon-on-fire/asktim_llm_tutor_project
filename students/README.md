# Students

Simulated student bots used to test the tutor. Each persona is a different "attack vector" — it tries to trigger a specific tutor failure mode (e.g. giving away the answer, going off-topic, lecturing instead of diagnosing).

## Structure

```
students/
  __init__.py      — package exports
  run_student.py   — shared LangGraph engine (one file, all personas)
  personas/
    chaotic_01.txt — LLM system prompt
    chaotic_01.md  — human-readable summary of what the persona tests
    ...
```

- **`run_student.py`** — the single bot engine. Select a persona by name (e.g. `"chaotic_01"`); the engine loads the matching `.txt` prompt from `personas/`.
- **`personas/*.txt`** — system prompts sent to the LLM to shape the student's behavior.
- **`personas/*.md`** — short human-readable descriptions (a few sentences explaining what the persona tests and how it behaves).

## Adding a new persona

Create two files in `personas/`:

1. `{name}.txt` — the LLM system prompt
2. `{name}.md` — a few sentences describing the persona for humans

No code changes needed. The bot engine discovers personas automatically.

## Available personas

| Name | Tests |
| ---- | ----- |
| `chaotic_01` | Academic integrity — scripted tactics (fake approval, pressure, direct asks, etc.) |
| `chaotic_02` | Academic integrity — unscripted, invents its own strategies |
| `chitchat_01` | Role adherence — off-topic chat (pizza, weather, breaks) |
| `clueless_01` | Helping lost students — vague confusion to trigger long lectures |

## Usage

```python
from students.run_student import get_next_student_message

msg = get_next_student_message(
    messages,                    # conversation so far (list of BaseMessage)
    prompt_name="chaotic_01",    # persona to use
    assignment="...",            # optional assignment text
    turn_size=10,                # optional planned student+tutor exchanges
)
```

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `OPENAI_API_KEY` | Yes | OpenAI API key. Fails immediately if not set. |
| `OPENAI_MODEL` | No | Model name (default: `gpt-5.2`). |
