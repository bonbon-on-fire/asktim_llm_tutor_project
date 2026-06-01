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
  --transcript transcript_0001 \
  --resume-from-turn 5 \
  --additional-turns 3 \
  --tutor-prompt tutor_05 \
  --tutor-provider gpt
```

See `ui/run_ui_raw_mini` for the interactive wrapper.

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
| `OPENAI_API_KEY` | Yes | OpenAI API key. Fails immediately if not set. |
| `OPENAI_MODEL` | No | Model name (default: `gpt-5.4`). |
