# Tutor

LangGraph-based Socratic tutor for MIT OCW humanities courses. The tutor guides students through assignments using guided discovery — it never gives the answer directly.

## Structure

```text
tutor/
  __init__.py               — package exports
  run_tutor.py              — LangGraph engine, system-prompt loading, response parsing
  run_tutor_mini.py         — resume/replay a raw transcript from a pivot turn with a new tutor
  prompts/
    tutor_01.txt            — baseline system prompt
    tutor_02.txt            — revised system prompt variant
    tutor_03.txt            — concise-response variant used in bundle runs
    tutor_04.txt            — updated Socratic guidance variant
    tutor_05.txt            — latest variant (active for prompt iteration)
```

- `run_tutor.py` builds the LangGraph, invokes the LLM, and parses structured JSON response fields (pedagogical reasoning + student-facing answer).
- `run_tutor_mini.py` forks a raw transcript at a pivot turn, replays the student side from file, and regenerates the tutor response using a new prompt or provider.
- Prompt versions are selected by name (for example `tutor_03`, `tutor_05`) and loaded from `tutor/prompts/`.
- `stream_tutor_reply()` exposes a token-streaming entry point used by [`main_ui/`](../main_ui/README.md). It yields visible answer characters as they arrive, hiding the JSON envelope and the `pedagogical-reasoning` field server-side via the `StudentAnswerExtractor` state machine.

### Multimodal figures (non-streaming path)

When an exercise ships figures under `curriculum/<course>/figures/` (see [`curriculum/README.md`](../curriculum/README.md)), the tutor can reason over the real image. Pass them via the `figures=` kwarg — a list of figure paths from [`utils.figures.discover_figures`](../utils/figures.py):

```python
from tutor import create_tutor_graph, load_system_prompt
from utils.figures import discover_figures

figures = discover_figures("cities_and_climate_change", "08")   # [Path(...spider_diagram.png)]
prompt = load_system_prompt("tutor_05", assignment_override="...")
graph = create_tutor_graph(prompt, figures=figures)             # figures bound to the graph
```

The figures are attached to the **latest student turn** as multimodal content (a `[text, image_url…]` block list that works for both GPT and Claude via LangChain) on every tutor call — one copy per turn. The message sanitizers handle both plain-string and multimodal-list content. **Curriculum figures** are still wired only into the non-streaming/batch path (transcript generation + judging); the deployed `main_ui/` streaming path does not auto-attach exercise figures yet. It does, however, carry multimodal **student-uploaded** images on the latest turn (same `[text, image_url…]` block shape, via [`utils/uploads.py`](../utils/uploads.py) → `build_multimodal_content`), so the streaming path is no longer text-only. See Phase 6 in the root [PLANNING.md](../PLANNING.md).

### Lecture transcripts

If a course ships `curriculum/<course>/lectures/*.txt`, those transcripts are folded into the assignment context by the caller's context builder (`internal_ui` and `main_ui`) via [`utils.lectures.load_lecture_transcripts`](../utils/lectures.py) before being passed as `assignment_override`. The tutor module itself needs no change — it just receives the enriched assignment text.

## How the tutor works

1. The system prompt is loaded from `prompts/<prompt_name>.txt`.
2. If an exercise is provided, the `<Assignment>...</Assignment>` block in the prompt is replaced with the exercise text.
3. The LLM receives the system prompt + conversation history and returns a JSON response:
   ```json
   {
     "pedagogical-reasoning": "internal reasoning about how to respond",
     "Student-facing-answer": "the message shown to the student"
   }
   ```
4. `parse_tutor_response()` extracts both fields. The student-facing answer is returned; reasoning is available for debugging.

## Usage

```python
from tutor import get_tutor_reply, create_tutor_graph, load_system_prompt

# One-shot (builds a new graph each call)
messages, answer_text = get_tutor_reply(
    messages,
    assignment_override="Your exercise text here...",
)

# Reuse graph across multiple turns
prompt = load_system_prompt("tutor_01", assignment_override="...")
graph = create_tutor_graph(prompt)
messages, answer_text = get_tutor_reply(messages, graph=graph)
```

### Mini continuation (resume from pivot turn)

```powershell
python -m tutor.run_tutor_mini \
  --persona-type chaotic \
  --transcript transcript_01 \
  --resume-from-turn 5 \
  --additional-turns 3 \
  --tutor-prompt tutor_05 \
  --tutor-provider gpt
```

See `internal_ui/run_ui_raw_mini` for the interactive wrapper.

### Streaming (used by `main_ui/`)

```python
from tutor.run_tutor import build_tutor_model, load_system_prompt, stream_tutor_reply
from langchain_core.messages import HumanMessage

model = build_tutor_model()                              # provider="gpt" (default) or "claude"
system_prompt = load_system_prompt("tutor_05", assignment_override="...")
messages = [HumanMessage(content="explain urban heat islands")]

for chunk in stream_tutor_reply(messages, model=model, system_prompt=system_prompt):
    if isinstance(chunk, tuple) and chunk[0] == "__done__":
        full_raw_json = chunk[1]                         # for parse_tutor_response()
        break
    print(chunk, end="", flush=True)
```

This yields one batch of visible characters per LLM token batch, then a final `("__done__", full_raw_json)` sentinel so the caller can recover the hidden `pedagogical-reasoning` field via `parse_tutor_response()`.

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `OPENAI_API_KEY` | For GPT | OpenAI API key. Required for the default `gpt` provider. |
| `OPENAI_MODEL` | No | OpenAI model name (default: `gpt-5.4`). |
| `ANTHROPIC_API_KEY` | For Claude | Anthropic API key. Required only when `build_tutor_model(provider="claude")` is used. |
| `ANTHROPIC_MODEL` | No | Anthropic model name (default: `claude-sonnet-4-6`). |
