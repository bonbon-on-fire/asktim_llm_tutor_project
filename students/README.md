# Students

Simulated student bots used to test the tutor. Each persona is a different "attack vector" — it tries to trigger a specific tutor failure mode (e.g. giving away the answer, going off-topic, lecturing instead of diagnosing).

## Structure

```text
students/
  __init__.py      — package exports
  run_student.py   — shared LangGraph engine (one file, all personas)
  personas/
    cooperative_01.txt — LLM system prompt   ┐
    cooperative_01.md  — human-readable summary │ three numbered variants
    cooperative_02.txt                          │ (01/02/03) per type
    cooperative_02.md                           ┘
    cooperative_03.txt / .md
    chaotic_01.txt / .md   …  chaotic_02, chaotic_03
    clueless_01.txt / .md  …  clueless_02, clueless_03
```

- `run_student.py` is the shared engine for all personas.
- `personas/*.txt` are LLM-facing persona prompts.
- `personas/*.md` are human-readable summaries of persona intent.
- Persona names are the **full stem** including the number: a run selects one by
  `prompt_name` (e.g. `"chaotic_01"`), which maps to
  `personas/<prompt_name>.txt`. There are **no** un-numbered base files —
  `prompt_name="chaotic"` does not resolve. `list_personas()` returns every
  `*.txt` stem.

## Adding a new persona

Create two files in `personas/`:

1. `{type}_{NN}.txt` — the LLM system prompt
2. `{type}_{NN}.md` — a few sentences describing the persona for humans

No code changes needed. The bot engine discovers personas automatically.

## Available personas

Three persona **types**, each with **three numbered variants** (`_01`/`_02`/
`_03`) that probe the same failure mode with a different strategy — `_01` is
**scripted** (a fixed tactic set), `_02` is **unscripted** (generates/adapts
tactics dynamically), `_03` is a **strategy sweep** (tracks what it has tried and
rotates to avoid repetition):

| Type | Tests |
| ---- | ----- |
| `cooperative_0N` | Good-student baseline: sincere, imperfect, non-adversarial. |
| `chaotic_0N` | Academic-integrity / tutor-vs-assistant boundary stressing (persistent answer-extraction, anti-capitulation). |
| `clueless_0N` | Lost-student, diagnosis-first: holds a stated misconception until specifically corrected. |

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
    prompt_name="chaotic_01",    # persona to use (full stem, incl. the number)
    assignment="...",            # optional assignment text
    turn_size=10,                # optional planned student+tutor exchanges
    figures=discover_figures("supply_chain_design", "4"),  # optional exercise figures
)
```

When `figures` are supplied (the same exercise figures the tutor sees), they're attached to the tutor's latest turn as multimodal content so the simulated student can reason over the image too. Plain-string and multimodal-list message content are both handled. Figures are optional — omit the kwarg for text-only runs.

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `OPENAI_API_KEY` | Yes | OpenAI API key. Fails immediately if not set. |
| `OPENAI_MODEL` | No | Model name (default: `gpt-5.4`). |
