# Cache-friendly tutor history: interleaved per-turn RAG + verbatim tutor output

**Date:** 2026-07-14
**Status:** Approved design — pending implementation plan
**Scope:** the live tutor streaming path in `main_ui` and `sandbox_ui`

## Terminology

This project's domain roles are **student** and **tutor** (and **system** for
instructions). They map onto the LLM API roles as: **student → `user`**,
**tutor → `assistant`**, **system → `system`**. This doc uses student/tutor
throughout; the API-role mapping is only relevant when building the request.

## Problem

Every turn we re-send the whole conversation to the model. Prompt caching is a
prefix match — content up to the first byte that changes is served at ~10% of
input cost; everything after the first change is billed at full price. Today the
per-turn RAG block is folded into the **leading** system message, *before* the
conversation history:

```
system(static) + rag(this turn)   ← rag changes every turn
student 1, tutor 1, student 2, tutor 2, ... student N
```

Because the RAG block changes every turn and sits ahead of the history, the
prefix diverges at the RAG block on every turn, so the **entire growing history
is re-billed at full price each turn** (~10x overpay on history tokens, growing
with conversation length). Only the static system prompt caches. This is the
default production configuration (`rag` context mode, Claude Sonnet 5).

## Verified findings (live, this session)

- The API accepts **multiple interleaved system messages** — a RAG system
  message after each student turn — on **claude-sonnet-5** and **claude-opus-4-8**.
  Each such system message must follow a student (`user`) turn and be either the
  last message or followed by a tutor (`assistant`) turn.
- **`langchain_anthropic` (1.4.4) rejects** this ("Received multiple
  non-consecutive system messages"), so the Claude path must use the **raw
  `anthropic` SDK** for the streaming call.
- **`langchain_openai` accepts** the interleaved structure, so the GPT path stays
  on langchain.

## Goals

1. Make the conversation history (student turns + their RAG + tutor replies)
   **cacheable turn-to-turn**, so only the current turn's new content is billed
   at full price.
2. Keep retrieved course material in the **instruction (system) channel** so the
   tutor never treats it as the student's words.
3. Replay the **verbatim full tutor output** (the raw JSON with both
   `pedagogical-reasoning` and `Student-facing-answer`) as the tutor turn — for
   byte-stable caching and to few-shot the output format.
4. Roll out safely behind a **per-conversation A/B**, default off.

## Non-goals

- No change to retrieval itself (top-k, week-scoping, fail-closed behavior).
- No change to legacy-mode conversations or to existing stored data.
- No move of the *whole* tutor stream off langchain (only the Claude cached path
  uses the raw SDK; legacy + GPT stay on langchain).

## Design

### 1. Cached-mode message structure

```
system(static prompt)                    ← leading; cache-marked
student 1  (text + figures / uploaded images)
system: rag 1                            ← retrieval used for turn 1
tutor 1    (verbatim raw JSON: {pedagogical-reasoning, Student-facing-answer})
student 2
system: rag 2
tutor 2    (verbatim raw JSON)
...
student N  (current student turn)
system: rag N (current retrieval)        ← last message
```

Each `rag_k` and `tutor_k` is fixed once turn `k` happened and is replayed
byte-identically on every later turn, so the whole history is a stable cacheable
prefix. Only `student N` + `rag N` are fresh each turn. Figures/uploaded images
remain attached to the **latest** student turn only (unchanged).

### 2. Storage (what makes replay byte-stable)

- **Per-turn RAG.** Replayed from stored retrieval records re-rendered through
  the existing deterministic `rag.retrieve.format_context`, so the block is
  identical each turn.
  - `sandbox_ui` already stores `retrieved_context` (JSON records) on the tutor
    `Message` — reuse it.
  - `main_ui` does **not**; add a nullable `retrieved_context` column to its
    `Message` (via **Alembic** migration — main_ui uses Alembic, not the boot
    reconciler), and persist `rc.records` in the chat route's done-handler,
    mirroring sandbox.
- **Verbatim tutor output.** Reconstructed canonically from the two fields
  already stored (`content` = student-facing answer, `pedagogical_reasoning`):
  `json.dumps({"pedagogical-reasoning": reasoning, "Student-facing-answer":
  answer}, ensure_ascii=False)` with fixed key order. Consistent across turns →
  caches; also few-shots the JSON envelope. **No new column** for the output.

### 3. Per-conversation A/B

- Add a nullable `history_mode` column to `Conversation` in both apps
  (`"cached"` | `"legacy"`; `NULL` = legacy). sandbox via `_reconcile_columns`;
  main_ui via Alembic.
- Assigned **once at conversation creation** by a random draw against an env
  ratio `TUTOR_CACHED_HISTORY_RATIO` (default **0.0** → all legacy; `0.5` → A/B;
  `1.0` → full rollout). Stored so continuations replay their mode.
- Threaded to the bridge like `context_mode` / `provider`.
- Because mode is fixed at creation, cached-mode conversations are always new and
  store per-turn RAG from turn 1 — **no legacy-migration path is needed**; old
  conversations stay legacy.

### 4. Provider sending

- **Claude (cached):** raw `anthropic` SDK —
  `client.messages.stream(system=<static, cache_control ephemeral>,
  messages=[…interleaved…])`, driving the existing `StudentAnswerExtractor` on
  the streamed text deltas (it already extracts only the `Student-facing-answer`
  chars; the raw stream yields the same JSON text). The terminal `("__done__",
  raw)` contract and `parse_tutor_response` normalization are unchanged.
- **GPT (cached):** langchain `ChatOpenAI` with interleaved `SystemMessage`s
  (verified accepted). OpenAI auto-caches the stable prefix.
- **Legacy (either provider):** unchanged — today's `_build_system_message`
  single-system path.

### 5. History shape + fail-closed

- Add a cached-mode variant of `get_history_for_tutor` returning, per prior turn,
  `{student_content, rag_records, tutor_raw}` so the bridge can assemble the
  interleaved list. The legacy history shape (`[{role, content}]`) is untouched.
- Fail-closed retrieval is unchanged: in `rag` context mode, if the **current**
  turn's retrieval yields no records, raise `RagUnavailableError` before any
  model call (the route turns it into an `event: error`).

### 6. Cache breakpoints (Claude)

- Mark the static system block with `cache_control: ephemeral`.
- Place a rolling `cache_control` breakpoint on the **last** message each turn
  (writes the growing prefix), plus an **intermediate** breakpoint roughly every
  15 message blocks to stay within Anthropic's 20-block cache lookback. Anthropic
  allows up to 4 breakpoints per request; a simple "every N blocks + last" scheme
  stays within that for realistic conversation lengths.

### 7. Testing

- **Unit:** the interleaved-message builder (history rows → exact ordered message
  list, correct roles and placement); the canonical tutor-JSON reconstruction
  (byte-stable across calls).
- **Live smoke (behind the flag):** one real 2–3 turn Claude conversation in
  cached mode asserting `usage.cache_read_input_tokens` grows on turn ≥2 (proves
  the history caches) and the reply parses cleanly; same smoke on GPT.
- Default `TUTOR_CACHED_HISTORY_RATIO=0.0` keeps CI and existing tests on the
  legacy path (no behavior change).

## Files affected (approximate)

- `main_ui/db/models.py` + new Alembic migration — `retrieved_context`,
  `history_mode` columns.
- `sandbox_ui/db/models.py` — `history_mode` column (RAG column already exists).
- `ui_core/services/conversation.py` (+ app wrappers) — cached-mode history
  builder; store RAG on main_ui.
- `main_ui/routes/chat.py` — persist `rc.records`; assign/thread `history_mode`.
- `sandbox_ui/routes/chat.py` — assign/thread `history_mode`.
- `ui_core/tutor_bridge.py` — build interleaved messages for cached mode; route
  Claude cached to the raw-SDK sender.
- `tutor/run_tutor.py` — raw-`anthropic` streaming helper + interleaved
  message/cache-breakpoint assembly; canonical tutor-JSON reconstruction helper.

## Rollout

1. Ship with `TUTOR_CACHED_HISTORY_RATIO=0.0` (no-op; new columns dormant).
2. Set to `0.5` to A/B on real traffic; compare per-turn cost (cache-read share)
   and tutor behavior between modes.
3. Raise to `1.0` once validated; legacy path remains as an instant fallback
   (set ratio back to 0.0).

## Risks & mitigations

- **Behavioral shift** from replaying past reasoning to the tutor: contained by
  the A/B — compare before rollout.
- **Bigger cached prefix** on long conversations (past RAG + full outputs):
  cached at ~10%, still a large net win vs. today; monitor via the A/B.
- **Raw-SDK streaming parity** with the langchain path (usage metadata,
  sanitization, done contract): covered by the live smoke asserting cache reads +
  clean parse, and by reusing `StudentAnswerExtractor` / `parse_tutor_response`.
