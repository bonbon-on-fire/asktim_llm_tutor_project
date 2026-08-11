# Tutor

LangGraph-based Socratic tutor for MIT OCW humanities courses. The tutor guides students through assignments using guided discovery — it never gives the answer directly.

## Structure

```text
tutor/
  __init__.py               — package exports
  run_tutor.py              — LangGraph engine, system-prompt loading, response parsing
  prompts/
    tutor_01.txt            — baseline system prompt
    tutor_02.txt            — revised system prompt variant
    tutor_03.txt            — concise-response variant used in bundle runs
    tutor_04.txt            — updated Socratic guidance variant
    tutor_05.txt            — refined Socratic guidance
    tutor_06.txt            — Socratic guidance variant
    tutor_07.txt            — tutor_05 guidance + math formatting + grounded lecture citations + anti-leakage
    tutor_08.txt            — deployed default: tutor_07 + a ## Language section (reply in the student's language) baked in (main_ui + sandbox_ui locked to this)
```

- `run_tutor.py` builds the LangGraph, invokes the LLM, and parses structured JSON response fields (pedagogical reasoning + student-facing answer).
- Prompt versions are selected by name (for example `tutor_03`, `tutor_08`) and loaded from `tutor/prompts/`. **`tutor_08` is the deployed default** (`DEFAULT_TUTOR` in both `main_ui` and `sandbox_ui`, and both apps are **locked** to it — the client can't override it). To revert to English-only, switch the default back to `tutor_07`.
- **`tutor_08`** is `tutor_07` with a **`## Language` section** baked in — the tutor detects the language of the student's latest message and writes its student-facing answer in that language (following mid-conversation switches), while keeping `pedagogical-reasoning`, the JSON field names, citation labels, and LaTeX in English.
- **`tutor_07`** layers on `tutor_05`'s Socratic guidance and adds:
  - **Math formatting** — write math as `\(...\)` (inline) / `\[...\]` (display) LaTeX, never `$`/`$$` (those stay literal currency), doubling every backslash (`\\(`, `\\frac{}{}`) so the JSON response stays valid.
  - **Grounded lecture citations** — when pointing a student to course material, cite the real **Week / Lesson / Video** coordinate (e.g. *"…in **Week 10, Lesson 1**, in the **DuPont Analysis** video"*), woven into a sentence. Labels come from `curriculum/<course>/lecture_index.json` via [`rag/retrieve.py`](../rag/README.md); the tutor may only cite a label present in the retrieved block, so it can't invent a lecture.
  - **Anti-leakage** — never expose the retrieval plumbing or its own citation rules to the student (no "retrieved material", "the lectures shown here", "I can't verify", etc.).
- `stream_tutor_reply()` exposes a token-streaming entry point used by [`main_ui/`](../main_ui/README.md). It yields visible answer characters as they arrive, hiding the JSON envelope and the `pedagogical-reasoning` field server-side via the `StudentAnswerExtractor` state machine.

### Roles

A *role* selects which prompt family the web apps (`main_ui`, `sandbox_ui`)
use, via a `role` URL query param (default `tutor`). Roles are declared in
`tutor/roles.py`:

- `role=tutor` → `tutor/prompts/`, default prompt `tutor_08` (the deployed
  default; both apps stay locked to their role's default prompt).
- `role=ta` → a future `ta/prompts/` folder — **not shipped**; requesting it
  404s until added.

**Adding a role** (e.g. `ta`):
1. Create `ta/prompts/ta_01.txt` (and any variants).
2. Register it in `tutor/roles.py`:
   `"ta": Role("ta", _REPO_ROOT / "ta" / "prompts", "ta_01")`.

Prompt names are unique per role (`tutor_*` vs `ta_*`); the web bridge resolves
a prompt's folder from its name, so no per-conversation role is stored.

### Multimodal figures (non-streaming path)

When an exercise ships figures under `curriculum/<course>/figures/` (see [`curriculum/README.md`](../curriculum/README.md)), the tutor can reason over the real image. Pass them via the `figures=` kwarg — a list of figure paths from [`utils.figures.discover_figures`](../utils/figures.py):

```python
from tutor import create_tutor_graph, load_system_prompt
from utils.figures import discover_figures

figures = discover_figures("cities_and_climate_change", "08")   # [Path(...spider_diagram.png)]
prompt = load_system_prompt("tutor_06", assignment_override="...")
graph = create_tutor_graph(prompt, figures=figures)             # figures bound to the graph
```

The figures are attached to the **latest student turn** as multimodal content (a `[text, image_url…]` block list that works for both GPT and Claude via LangChain) on every tutor call — one copy per turn. The message sanitizers handle both plain-string and multimodal-list content.

This now applies to **both** paths. The non-streaming/batch path (transcript generation + judging) binds figures to the graph as shown above. The deployed `main_ui/` (and `sandbox_ui/`) **streaming** path auto-attaches the same exercise figures: [`services/tutor_bridge.py`](../main_ui/services/tutor_bridge.py) calls `discover_figures(course, exercise)` and merges the results with any student-uploaded images, then attaches them to the latest student turn on every call (per-call history is text-only, so re-attaching each turn keeps the figure in view). `sandbox_ui/` skips this when the tester typed a one-off custom course/exercise, since those have no figures folder on disk. See Phase 6 in the root [PLANNING.md](../PLANNING.md).

### Lecture transcripts

If a course ships `curriculum/<course>/lectures/*.txt`, those transcripts are folded into the assignment context by the caller's context builder (`internal_testing` and `main_ui`) via [`utils.lectures.load_lecture_transcripts`](../utils/lectures.py) before being passed as `assignment_override`. The tutor module itself needs no change — it just receives the enriched assignment text.

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

### What the tutor receives each turn

**By default** (cache-friendly interleaved history, gated by `TUTOR_CACHED_HISTORY` —
see [Prompt caching](#prompt-caching) below), each turn is laid out as an
interleaved sequence rather than three flat blocks: a leading **SYSTEM message**
carries the static tutor prompt plus assignment context (the exercise, the
tutor-only answer key); then, for each prior turn, the student's message, that
turn's retrieved RAG as its **own** system message (when there was any), and the
tutor's **verbatim past reply** — the full `{"pedagogical-reasoning": ...,
"Student-facing-answer": ...}` JSON, not just the student-facing text; then the
**current student turn** (its text plus any figures / uploaded files), followed
by the current turn's retrieved RAG as the last message. Because every replayed
rag/tutor block is byte-identical turn to turn, the tutor's own past reasoning
**is** replayed back to it — intentional: it keeps the conversation prefix
byte-stable for prompt caching and few-shots the JSON output format — and the
whole growing history becomes a stable, cacheable prefix rather than just the
static prompt.

Set `TUTOR_CACHED_HISTORY=0`/`false`/`no`/`off` to fall back to the legacy path
(also always used by the non-streaming graph path, e.g. the batch runners in
`internal_testing/`): one **SYSTEM message** (the tutor prompt plus assignment
context, with any per-turn RAG appended **after** the static cacheable prompt),
the **conversation history** (prior student turns plus the tutor's
student-facing answers only, with the hidden `pedagogical-reasoning` field
**stripped**), and the **current student turn**. The tutor never re-receives
its own past reasoning in this legacy mode.

Either way, retrieved RAG material always rides in a system message — never
prepended to the student's turn — so the student's words stay clean; LangChain
has no "developer" role, so the system message is used. RAG is the **shared
default** context mode whenever a course has no custom context; when RAG
retrieval yields no results, the bridge raises `RagUnavailableError` before the
model is called, surfacing an error to the student rather than degrading to
full context — see [`rag/README.md`](../rag/README.md#mandatory-rag-fail-closed).

## Function reference (`run_tutor.py`)

Everything in `__init__.py`'s `__all__` is public; the rest is internal (leading
underscore) but documented here for maintainers.

### Model & system prompt

- **`build_tutor_model(provider="gpt")`** — construct the LangChain chat model.
  `"gpt"` → `ChatOpenAI` (`OPENAI_MODEL`, default `gpt-5.4`); `"claude"` →
  `ChatAnthropic` (`ANTHROPIC_MODEL`, default `claude-sonnet-5`, built with
  `max_tokens=8192` and thinking disabled — the tutor streams a strict two-field
  JSON via a char-level extractor, so adaptive thinking is turned off and the low
  unknown-model token fallback is overridden). Exposed so the streaming path can
  call `model.stream(...)` directly. **Both chat apps now pick the provider per
  call** (`main_ui` → `claude`/Sonnet 5 by default; `sandbox_ui` → the tester's
  wizard choice), resolved via `ui_core.tutor_bridge._resolve_provider`.
- **`load_system_prompt(prompt_name="tutor_01", assignment_override=None)`** — read
  `prompts/<prompt_name>.txt`; when `assignment_override` is given, replace the
  `<Assignment>…</Assignment>` block with it. Uses a regex *replacement function*
  so LaTeX backslashes in the assignment aren't interpreted as escapes. Raises
  `FileNotFoundError` (listing available prompts) if the prompt is missing.
- **`_require_openai_api_key()` / `_require_anthropic_api_key()`** — return the key
  from the environment or raise `RuntimeError`.

### Graph & tutor turn

- **`TutorState`** — the LangGraph state: a `TypedDict` with `messages` accumulated
  via `operator.add`, plus an optional `retrieved_context` string carried through
  the graph path so per-turn RAG material can be folded into the system message.
- **`create_tutor_graph(system_prompt, *, provider="gpt", figures=None)`** — build
  and compile the single-node graph. Its `tutor_node` sanitizes messages, runs the
  non-student-like guard, optionally attaches `figures` to the latest student turn,
  caches the conversation prefix (Anthropic only), invokes the model, and
  normalizes the reply. `figures` is bound at build time
  (constant per conversation), so each turn re-sends exactly one copy.
- **`get_tutor_reply(messages, assignment_override=None, *, graph=None, prompt_name="tutor_01", figures=None, retrieved_context="")`**
  — main non-streaming entry point. Builds its own graph when none is passed;
  returns `(updated_messages, student_facing_answer_text)`. `figures` applies only
  when it builds its own graph. `retrieved_context`, when given, is appended to the
  system message after the cacheable prompt (RAG mode).
- **`_looks_non_student_like(text)`** — heuristic that flags empty input or
  tutor/system artifacts (e.g. `pedagogical-reasoning`, `<assignment>`, ` ```json `)
  — i.e. prompt-injection or malformed input.
- **`_build_invalid_input_reply()`** — canned strict-JSON `AIMessage` asking the
  student to restate their message; returned when the guard trips.

### Response parsing & normalization

- **`parse_tutor_response(content)`** — extract `(reasoning, answer)` from the
  tutor's JSON. Tries raw JSON → fenced code block → balanced-brace extraction, and
  parses with `strict=False` so literal newlines inside string values (multi-line
  markdown tables) don't break it. If all three candidates fail to parse, each is
  retried through `_repair_latex_json()` before giving up — a fallback for when the
  tutor emits LaTeX with a single (rather than doubled) backslash, e.g. `\(x^2\)`,
  which is an invalid JSON escape that would otherwise make the whole reply fail to
  parse and leak raw JSON to the student. Either field may be `None` on failure.
- **`_repair_latex_json(s)`** — doubles stray LaTeX backslashes (`\(`, `\frac`,
  `\sum`, `\theta`, …) so an otherwise-invalid tutor reply becomes valid JSON, while
  leaving the tutor's intentional escapes untouched: `\\`, `\"`, `\uXXXX`, and real
  `\n` newlines (distinguished from LaTeX commands like `\nu`/`\ne` by checking the
  next character isn't a lowercase letter). Used only as a fallback after a strict
  parse fails, so well-formed replies are never altered.
- **`_normalize_tutor_ai_message(msg)`** — force any model output into the strict
  two-field JSON shape, filling fallback text when a field is missing, so
  downstream consumers always see `pedagogical-reasoning` + `Student-facing-answer`.
  Preserves the raw response's `usage_metadata` / `response_metadata` on the
  rebuilt `AIMessage` so cost accounting can still read token usage off the final
  message.
- **`_fenced_json(text)`** — pull JSON out of the first ` ```json … ``` ` fence.

### Message sanitizing & multimodal content

- **`_sanitize_text_for_transport(text)`** — drop control chars and UTF-16
  surrogate code points that break JSON request encoding (keeps tab/newline/CR).
- **`_content_text(content)`** — extract the plain-text portion of a message whose
  content may be a string or a multimodal block list (image blocks contribute none).
- **`_sanitize_content(content)`** — sanitize a string, or the `text` blocks of a
  multimodal list, leaving `image_url` blocks untouched.
- **`_sanitize_message_content(msg)`** — return a clean copy of a `BaseMessage`
  preserving its type (`Human`/`AI`/`System`).
- **`_attach_figures_to_last_human(messages, figures)`** — rewrite the last
  `HumanMessage` in place to carry `figures` as multimodal content; no-op if none.

### Prompt caching

Anthropic only — OpenAI auto-caches long prefixes, so the mechanisms below are
no-ops there (and for any other provider). Caching is billing/latency-only and
never changes the model's output; Anthropic silently ignores a marker below its
minimum cacheable length, so all of the below is always safe.

**Cache-friendly interleaved history (default, streaming path).** Gated by
`TUTOR_CACHED_HISTORY` (default ON — `0`/`false`/`no`/`off` falls back to
legacy; see [`ui_core.tutor_bridge.cached_history_enabled()`](../ui_core/README.md)).
`tutor/cached_history.py`'s `build_message_plan()` lays out each prior turn as
student → system(rag, if any) → tutor(verbatim JSON), then the current student
turn → system(current rag) as the last message; `tutor_output_json()` produces
the canonical, byte-stable `{"pedagogical-reasoning": ..., "Student-facing-answer":
...}` string replayed for each past turn. `stream_tutor_reply_anthropic_raw()`
sends that plan through the raw `anthropic` SDK, since `langchain_anthropic`
rejects multiple non-consecutive system messages; the GPT path stays on
langchain, which accepts the interleaved `SystemMessage`s. Because every
replayed rag/tutor block is identical turn to turn, the whole growing history
becomes a stable cacheable prefix — only the newest student turn and its RAG
are billed at full input price, and the rest is served from cache reads at a
fraction of that cost; the saving grows with conversation length. Cache
breakpoints are tail-anchored and capped so a request never exceeds
Anthropic's 4-`cache_control`-per-request limit.

**Legacy path** — used when `TUTOR_CACHED_HISTORY` is falsy, and always for the
non-streaming graph path (`get_tutor_reply`, used by the batch runners in
`internal_testing/`):

- **`_build_system_message(system_prompt, model, retrieved_context="")`** — build
  the tutor `SystemMessage`. On `ChatAnthropic` the prompt is wrapped in a text block
  marked `cache_control: {"type": "ephemeral"}` so the large, constant
  assignment-context prefix is served from cache on later turns; otherwise it stays a
  plain string. When `retrieved_context` is given (RAG mode), it is appended **after**
  the cacheable prompt block as its own segment, so the per-turn retrieved material
  reaches the tutor via the system message without disturbing the cache prefix.
  (LangChain has no "developer" role, so the system message carries it.) Shared with
  the UI path via `ui_core.tutor_bridge._build_system_message`.
- **`_cache_last_message(messages, model)`** — mark the newest turn's last content
  block with an ephemeral cache breakpoint. Prompt caching is a prefix match, so
  caching the latest turn writes the whole conversation-so-far to cache and the
  *next* turn re-reads that prefix at ~0.1x input cost instead of full price.
  Applied in the graph path (`tutor_node`) always, and in the streaming path
  (`stream_tutor_reply`) only under this legacy fallback; pairs with the cached
  system prefix (2 breakpoints, under Anthropic's limit of 4). Because only the
  static prompt caches here, the growing conversation history itself is re-billed
  at full price each turn — the gap the cache-friendly default above closes.

### Streaming

- **`StudentAnswerExtractor`** — a character-level state machine
  (`find_field → find_colon → find_open_quote → in_value → done`) that walks the
  accumulating token buffer and emits **only** the chars inside the
  `Student-facing-answer` string value, with full JSON escape handling (including
  `\uXXXX`, waiting for split escape sequences across chunks). Only the escapes the
  tutor actually intends (`\n`, `\t`, `\r`, `\"`, `\\`, `\/`, `\uXXXX`) are resolved;
  a lone `\b` or `\f` is deliberately left as a literal backslash since it's almost
  always LaTeX (`\beta`, `\frac`) rather than a backspace/formfeed — so LaTeX
  backslashes survive intact while streaming. `feed(chunk)` returns newly-visible
  chars; `.found_answer` and `.buffer` expose progress and the full raw text for the
  final parse.
- **`stream_tutor_reply(messages, *, model, system_prompt, retrieved_context="")`**
  — generator that yields visible answer chunks, then a final
  `("__done__", full_raw_json, ai_message)` tuple: `full_raw_json` recovers the
  hidden reasoning via `parse_tutor_response`, and `ai_message` is the terminal
  `AIMessage` carrying `usage_metadata` / `response_metadata` for cost accounting
  (the canned-reply path carries no usage). `retrieved_context`, when given, is
  folded into the system message after the cacheable prompt (RAG mode). Bypasses
  the graph to use `model.stream(...)`; mirrors the non-student-like guard; falls
  back to emitting the parsed answer if the incremental extractor never locates the
  field.

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

### Streaming (used by `main_ui/`)

```python
from tutor.run_tutor import build_tutor_model, load_system_prompt, stream_tutor_reply
from langchain_core.messages import HumanMessage

model = build_tutor_model()                              # provider="gpt" (default) or "claude"
system_prompt = load_system_prompt("tutor_06", assignment_override="...")
messages = [HumanMessage(content="explain urban heat islands")]

for chunk in stream_tutor_reply(messages, model=model, system_prompt=system_prompt):
    if isinstance(chunk, tuple) and chunk[0] == "__done__":
        full_raw_json = chunk[1]                         # for parse_tutor_response()
        ai_message = chunk[2]                             # usage_metadata for cost accounting
        break
    print(chunk, end="", flush=True)
```

This yields one batch of visible characters per LLM token batch, then a final `("__done__", full_raw_json, ai_message)` sentinel so the caller can recover the hidden `pedagogical-reasoning` field via `parse_tutor_response()` and the turn's token usage from `ai_message`.

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `OPENAI_API_KEY` | For GPT | OpenAI API key. Required for the default `gpt` provider. |
| `OPENAI_MODEL` | No | OpenAI model name (default: `gpt-5.4`). |
| `ANTHROPIC_API_KEY` | For Claude | Anthropic API key. Required only when `build_tutor_model(provider="claude")` is used. |
| `ANTHROPIC_MODEL` | No | Anthropic model name (default: `claude-sonnet-4-6`). |
