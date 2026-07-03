# Students

Simulated student bots used to test the tutor. Each persona is a different "attack vector" — it tries to trigger a specific tutor failure mode (e.g. giving away the answer, going off-topic, lecturing instead of diagnosing).

## Structure

```text
students/
  __init__.py      — package exports
  run_student.py   — shared LangGraph engine (one file, all personas)
  personas/
    cooperative.txt — LLM system prompt
    cooperative.md  — human-readable summary of what the persona tests
    chaotic.txt
    chaotic.md
    clueless.txt
    clueless.md
```

- `run_student.py` is the shared engine for all personas.
- `personas/*.txt` are LLM-facing persona prompts.
- `personas/*.md` are human-readable summaries of persona intent.

## Adding a new persona

Create two files in `personas/`:

1. `{name}.txt` — the LLM system prompt
2. `{name}.md` — a few sentences describing the persona for humans

No code changes needed. The bot engine discovers personas automatically.

## Available personas

One persona per type (variety comes from `temperature=0.7`, not multiple files):

| Name | Tests |
| ---- | ----- |
| `cooperative` | Good-student baseline: sincere, imperfect, non-adversarial. |
| `chaotic` | Academic-integrity / tutor-vs-assistant boundary stressing (persistent answer-extraction, anti-capitulation). |
| `clueless` | Lost-student, diagnosis-first: holds a stated misconception until specifically corrected. |

Each persona encodes an epistemic level, an error budget, a per-type behavior
contract, casual texting voice, and a per-turn micro-structure. See
`docs/superpowers/specs/2026-07-02-student-persona-consolidation-design.md`.

All personas also inherit shared role constraints from the engine (student voice only, no tutor-like framing, concise replies).

## Usage

```python
from students.run_student import get_next_student_message
from utils.figures import discover_figures

msg = get_next_student_message(
    messages,                    # conversation so far (list of BaseMessage)
    prompt_name="chaotic",       # persona to use
    assignment="...",            # optional assignment text
    turn_size=10,                # optional planned student+tutor exchanges
    figures=discover_figures("cities_and_climate_change", "08"),  # optional exercise figures
)
```

When `figures` are supplied (the same exercise figures the tutor sees), they're attached to the tutor's latest turn as multimodal content so the simulated student can reason over the image too. Plain-string and multimodal-list message content are both handled. Figures are optional — omit the kwarg for text-only runs.

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `OPENAI_API_KEY` | Yes | OpenAI API key. Fails immediately if not set. |
| `OPENAI_MODEL` | No | Model name (default: `gpt-5.4`). |
