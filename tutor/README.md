# Tutor

LangGraph-based Socratic tutor for MIT OCW humanities courses. The tutor guides students through assignments using guided discovery — it never gives the answer directly.

## Structure

```
tutor/
  __init__.py          — package exports
  run_tutor.py         — LangGraph engine, system-prompt loading, response parsing
  prompts/
    tutor_01.txt       — system prompt (Socratic rules, role boundaries, output format)
```

- **`run_tutor.py`** — builds the LangGraph, invokes the LLM, and parses the structured JSON response (pedagogical reasoning + student-facing answer).
- **`prompts/tutor_01.txt`** — the system prompt. Contains Socratic tutoring rules, role-adherence boundaries, grading constraints, and a default `<Assignment>` block that gets replaced at runtime with the actual exercise text.

## How the tutor works

1. The system prompt is loaded from `prompts/tutor_01.txt`.
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

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `OPENAI_API_KEY` | Yes | OpenAI API key. Fails immediately if not set. |
| `OPENAI_MODEL` | No | Model name (default: `gpt-5.2`). |
