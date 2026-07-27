# Enforce JSON Mode on Tutor Output

**Date:** 2026-07-25
**Status:** Approved — ready for implementation plan
**Source:** 07/23 meeting decision — "Fix output formatting at the root by enforcing
JSON mode on LangChain, rather than patching individual symptoms (LaTeX issues,
pedagogical-reasoning leaks)."

## Problem

The tutor is instructed by prompt to return a two-field JSON object
(`pedagogical-reasoning`, `Student-facing-answer`) but nothing *enforces* it. The
output is recovered by a best-effort parse/repair/normalize layer
(`parse_tutor_response`, `_repair_latex_json`, `_collapse_over_escaped_newlines`,
`_normalize_tutor_ai_message`, `StudentAnswerExtractor`). Two failure modes seen in
production (observed on Claude, the default, at the 07/23 course-staff session):

1. **Pedagogical-reasoning leak** — the hidden reasoning field surfaces in the
   student-facing answer.
2. **Malformed JSON** — single-escaped LaTeX backslashes (`\(`, `\frac`) make
   `json.loads` reject the whole reply, tripping the "I could not generate a valid
   response" fallback.

Both are symptoms of relying on the model to hand-serialize valid JSON. Enforcing
structured output at the API layer removes them by construction.

## Goals

- Guarantee well-formed, two-field tutor output on every live path.
- Preserve today's **token-by-token streaming** of the student-facing answer.
- Preserve prompt-cache economics (cache hits on the static prefix each turn).
- Provide an instant, env-flag rollback to the current best-effort path.

## Non-goals

- Changing the two-field schema or the tutor prompt's content.
- Removing the best-effort parse/repair layer (it stays as the gate-off fallback).
- Any UI/frontend change — the SSE delta contract is unchanged.

## Key constraint: enforcement mechanism differs by provider

- **Anthropic (Claude)** has no plain `json_object` response format. Enforcement =
  **tool-forcing**: force a single tool call with our schema; the answer arrives as
  the tool's `input`. When streamed, the tool input arrives as `input_json_delta`
  fragments (raw SDK) or `tool_call_chunks` args (langchain), **not** as `.content`
  text.
- **OpenAI (GPT)** has native `response_format` (`json_schema`, `strict: true`) that
  still **streams as ordinary content text** — so the existing extractor keeps
  working unchanged, only guaranteed-valid now.

The elegance: the tool `input` JSON has the **exact same shape**
(`{"pedagogical-reasoning": …, "Student-facing-answer": …}`) the
`StudentAnswerExtractor` state machine already walks. So the extractor needs **no
change** — only the *source* of the text fragments it is fed changes (from
`text_stream` to `input_json_delta` / `tool_call_chunks`).

## Architecture

### 1. `tutor/json_mode.py` (new)

Single owner of the enforcement contract, so every path reads the same thing:

- `json_mode_enabled() -> bool` — reads `TUTOR_JSON_MODE`, **default ON**. Mirrors
  `cached_history_enabled()`: `off/0/false/no` → legacy best-effort path; anything
  else (incl. unset) → enforced.
- `TUTOR_TOOL_NAME = "tutor_reply"`.
- Schema constants: two required string fields `pedagogical-reasoning` and
  `Student-facing-answer`, `additionalProperties: false`.
- `anthropic_tool_kwargs() -> dict` → `{"tools": [ {name, description, input_schema} ],
  "tool_choice": {"type": "tool", "name": "tutor_reply"}}` for the raw SDK.
- `openai_response_format() -> dict` → `{"type": "json_schema", "json_schema":
  {"name": "tutor_reply", "schema": {...}, "strict": true}}` for langchain ChatOpenAI.

### 2. Claude cached path — production default (`stream_tutor_reply_anthropic_raw`)

Gate on → pass `**anthropic_tool_kwargs()` into `client.messages.stream(...)`. The
model emits one forced `tool_use` block; iterate the stream's **events** and feed
each `delta.partial_json` (`input_json_delta`) to the unchanged
`StudentAnswerExtractor`. Recovery is **authoritative**: read
`stream.get_final_message()` → the `tool_use` block's `.input` (a real dict) → build
the normalized two-field JSON directly, skipping `parse_tutor_response`. Gate off →
today's exact `for text in stream.text_stream:` path.

`thinking={"type": "disabled"}` stays (already required, and forced tool_choice is
incompatible with extended thinking anyway).

### 3. GPT path + non-streaming graph

`build_tutor_model`:
- gpt + gate on → bind `openai_response_format()`. GPT cached loop and legacy loop
  keep `StudentAnswerExtractor` on `chunk.content` untouched; non-streaming
  `invoke` returns valid-JSON content → `parse_tutor_response` always succeeds.
- claude + gate on → bind tools+tool_choice (via `.bind_tools(..., tool_choice=…)`).
  Used only by the **legacy** claude streaming path (`TUTOR_CACHED_HISTORY=off`) and
  the claude **graph invoke**. The langchain streaming loop reads `tool_call_chunks`
  args (fed to the same extractor) instead of `.content`; invoke reads
  `response.tool_calls[0]["args"]`.

The production claude cached path uses the **raw SDK** (§2), not this bound model, so
claude enforcement lives in two spots that both read the schema from
`tutor/json_mode.py`.

### 4. Recovery, cost, caching

- **Recovery:** enforced output comes from the structured dict (raw SDK
  `tool_use.input`; langchain `tool_calls`), so reasoning-leak and malformed-JSON are
  gone by construction. Best-effort layer retained for gate-off → instant rollback.
- **Cost:** tool_use usage is reported identically; `_anthropic_usage_message`
  unchanged. Tool definitions add a small constant input-token cost that rides
  *inside* the cached prefix (tools precede the cache-marked system block), so cache
  hits are preserved.
- **Caching:** verified by the turn-2 `cache_read == turn-1 cache_write` smoke test.

## Data flow (claude cached, gate on)

```
bridge.stream_tutor_reply (cached, claude)
  -> stream_tutor_reply_anthropic_raw(plan, ..., images_by_student)
       build_anthropic_request(...)               # unchanged
       client.messages.stream(system, messages, **anthropic_tool_kwargs())
       for event in stream:                         # input_json_delta fragments
           extractor.feed(event.delta.partial_json) -> visible chars -> yield
       final = stream.get_final_message()
       reasoning, answer = final.tool_use.input     # authoritative dict
       yield ("__done__", normalized_json, usage_msg)
```

## Error handling

- Missing/failed tool call (model returns no tool_use, empty input, network error):
  fall back to the existing `_normalize_tutor_ai_message` "could not generate a valid
  response" path off the extractor buffer — no new failure surface.
- Gate off everywhere → byte-identical to current behavior.

## Testing (TDD, red-first)

1. `StudentAnswerExtractor` fed tool-input deltas yields the same visible text as
   the equivalent free-text JSON.
2. Raw-SDK path with a faked event stream emits deltas and recovers reasoning from
   `tool_use.input`.
3. Gate off → raw-SDK path is byte-identical to today (no tools in request).
4. `build_tutor_model` binds `response_format` for gpt / tools for claude **only**
   when the gate is on.
5. A LaTeX-heavy answer (`\(\frac{a}{b}\)`, embedded newlines) round-trips correctly
   through the extractor from *valid* JSON.
6. `json_mode_enabled()` gate semantics match `cached_history_enabled()`.

## Rollout

- `TUTOR_JSON_MODE` env flag, default **ON**. `=off/0/false/no` reverts to the
  best-effort parse path with no redeploy.

## Scope

Full scope: §2 (production claude cached) + §3 (gpt, legacy claude, non-streaming) so
the flag means one thing on every path. §2 is the essential deliverable; §3 is
consistency and can be split into a follow-up commit if needed.
