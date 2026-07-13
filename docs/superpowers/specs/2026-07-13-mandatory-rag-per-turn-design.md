# Spec 1 — Mandatory per-turn RAG (both apps)

Date: 2026-07-13
Status: Design approved; implementation plan pending.

## Goal

Every tutor turn retrieves course material per turn. RAG becomes the **default
and mandatory** context mode: if retrieval cannot produce grounding for the
turn, the turn **fails closed** — the bridge raises, the existing chat error
banner ("Something went wrong, please try again") shows, and **no model call is
made**. This applies identically to `main_ui` and `sandbox_ui`, because the
logic lives in the shared `ui_core.TutorBridge` base.

Non-goals (deferred to Spec 2): removing the sandbox custom-context feature and
its persisted DB columns. Custom context continues to work in Spec 1.

## Background / current state

Per-turn RAG plumbing already exists end to end:

- `tutor/run_tutor.py` carries `retrieved_context` through `TutorState` and folds
  it into the **system** message *after* the `cache_control` breakpoint
  (`_build_system_message`), so the static prefix stays cache-eligible and the
  student's turn stays pristine. Both the non-streaming graph path and
  `stream_tutor_reply` accept `retrieved_context`.
- `rag/` provides `retrieve_scored` / `format_context` / `to_records` /
  `has_index`, with `max_week` week-scoping.
- `ui_core.tutor_bridge.TutorBridge` is the shared base; `main_ui` uses it
  directly (its `retrieved_context()` hook returns empty — **no RAG today**),
  while `SandboxTutorBridge` overrides the hooks to add RAG + custom-context +
  include-toggle behavior gated by `context_mode`.
- `internal_testing/run_transcript_rag.py` drives RAG in batch simulations.

So RAG is live in sandbox (behind the mode toggle) and in the batch runner, but
**production `main_ui` runs `full_context`** (whole lecture corpus baked into the
prompt). The gap this spec closes: make RAG the shared default, make it
mandatory, and fail closed when it is unavailable.

## Design

### 1. Lift the RAG core into `ui_core.TutorBridge`

Move the reusable pieces out of `sandbox_ui/services/tutor_bridge.py` into the
base `TutorBridge` so both apps run one implementation:

- `_resolve_context_mode(course, has_custom, requested)` — mode precedence (see
  §2).
- `_week_for_exercise(exercise)` — numeric exercise/practice number → `max_week`,
  else `None`.
- `retrieved_context()` — in `rag` mode, embeds the **raw student turn**, runs
  `retrieve_scored(course, query, max_week=...)`, returns
  `RetrievedContext(text=format_context(...), records=to_records(...))`. Wrapped
  in try/except that returns an **empty** `RetrievedContext` on any failure
  (embedding/search error). Non-rag → empty.
- Context-mode-aware `build_assignment_text` — in `rag` / `exercise_only` it
  drops course/syllabus/lectures (retrieved or omitted), keeping the about-block
  + exercise + tutor-only solution key. `full_context` is today's behavior.
- `prepare_ctx` — resolves and stores `context_mode` into the per-call ctx.
- `cache_key` — base gains `context_mode` in the tuple (mode changes the built
  prompt).

`SandboxTutorBridge` keeps **only** its extensions on top: custom-context
overrides (`course_text`/`exercise_text`/`syllabus_text`/`lectures_text`/
`custom_tutor_prompt`), the `include_course`/`include_syllabus`/`include_lectures`
toggles, and the `has_custom` handling. Its RAG behavior is inherited, not
duplicated. No behavior change for sandbox's existing modes.

`main_ui/services/tutor_bridge.py` keeps its thin `TutorBridge()` instance and
current public signatures — it inherits RAG for free. Routes need no change; the
reply dict already carries `retrieved` (was always `[]`, now populated on rag
turns).

### 2. Mode resolution

Precedence, highest first:

1. Explicit `requested` mode (sandbox's per-conversation toggle), when valid.
2. `TUTOR_CONTEXT_MODE` env (deploy-wide override).
3. **Default `rag`** whenever there is a `course` and no custom context.

Degrade rule: `rag` degrades to `full_context` **only** when `has_custom` (a
tester's pasted context genuinely cannot be retrieved). **A missing index does
NOT degrade** — the mode stays `rag` and hits the fail-closed check in §3. This
is what makes "course has no index → refuse" hold.

Consequence: `full_context` is never a default. It is reached only by (a)
explicit selection, (b) the env override, or (c) `has_custom` auto-degrade
(sandbox custom context — removed in Spec 2). In production `main_ui`,
`full_context` is unreachable unless the env var is set.

### 3. Fail closed (new, shared)

When the effective mode is `rag`, the turn requires ≥1 retrieved chunk. All
three failure triggers collapse to "empty records":

- course has **no index**,
- retrieval returned **zero chunks** (incl. everything filtered out by
  `max_week`),
- retrieval **threw** (caught inside `retrieved_context()`).

In both `get_tutor_reply` and `stream_tutor_reply`, right after
`retrieved_context()` and **before any model call**:

> if `context_mode == "rag"` and `rc.records` is empty → raise
> `RagUnavailableError`.

`RagUnavailableError` is a new exception defined in `ui_core.tutor_bridge`.
Non-rag modes never raise.

`stream_tutor_reply` is a generator; the check runs on first iteration, before
the model is contacted, so no tokens are streamed and no model cost is incurred
beyond the single failed/empty embedding query.

### 4. Error surfacing (reuses existing plumbing)

Both apps' `/api/chat` routes already iterate the bridge stream inside
`try/except` and emit `event: error` on any exception
(`main_ui/routes/chat.py`, `sandbox_ui/routes/chat.py`). The frontend
(`static/js/chat.js`) shows the bottom banner **"Something went wrong, please
try again"** and rolls back the optimistic student + tutor bubbles, restoring the
composer text.

Therefore raising `RagUnavailableError` ⇒ error banner + no tutor bubble
rendered + **no tutor row persisted** (the `complete_exchange_tutor` path never
runs) + no model cost. No new UI, no canned tutor reply, nothing misleading
about restating the student's message.

Note (pre-existing, unchanged): the student message row is committed up front
before streaming, so the student's turn persists in the DB even though the UI
optimistically rolls its bubble back on error. This is existing behavior for any
stream error and is out of scope here.

### 5. Scope of effect

- `main_ui`: inherits the shared behavior. All three current courses
  (`cities_and_climate_change`, `mathematics_for_cs`, `supply_chain_design`)
  have a built `rag_index`, so main_ui goes to RAG on deploy. A turn where
  retrieval yields nothing gets the error banner instead of a model answer.
- `sandbox_ui`: same fail-closed rule in `rag` mode. Explicit `full_context` /
  `exercise_only` / custom-context modes still answer normally (no raise). A
  tester on a no-index course who does not pick a mode now hits the error banner
  and must explicitly choose `full_context`/`exercise_only` to tutor it —
  consistent with the mandatory-RAG model.

### 6. UX note (accepted)

A student turn that legitimately retrieves zero chunks would be refused. This is
rare: week-agnostic docs (course description, syllabus, key concepts, OCW
content) carry no week and are always in scope, so zero-chunks in practice means
an empty/absent index rather than a benign off-topic message. Accepted under the
fail-closed choice.

## Testing

All offline — no real LLM/embedding/network calls.

- `ui_core/test_tutor_bridge.py` (update):
  - rag mode + **stubbed empty/failed** retrieval → asserts `RagUnavailableError`
    is raised and **no upstream model call was recorded** (neither the graph nor
    the stream path invokes the model).
  - rag mode + **stubbed chunk** → normal path: single clean student turn, the
    retrieved block routed to the **system channel** (`retrieved_context` arg),
    not onto a user turn.
  - `exercise_only` mode → normal path, no raise, no retrieved block.
  - The existing "base never retrieves" assertion is replaced by the above (the
    base now retrieves by default).
- Route-level assertion (main_ui and/or sandbox chat route test): a rag turn
  whose retrieval is stubbed empty produces an `event: error` SSE frame (and no
  `done`), exercising the raise → error-frame path.
- `build_assignment_text` in `rag` mode drops course/syllabus/lectures while
  keeping the exercise (offline, filesystem-shaped temp course).

## Files touched (anticipated)

- `ui_core/tutor_bridge.py` — lift RAG core, add `RagUnavailableError`, fail-closed
  checks in both public methods, mode resolution, `context_mode` in `cache_key`.
- `sandbox_ui/services/tutor_bridge.py` — drop the now-shared helpers; keep only
  custom-context / include-toggle extensions calling the base.
- `ui_core/test_tutor_bridge.py` — updated assertions per Testing.
- One route-level test (main_ui or sandbox) — assert the `event: error` frame.
- READMEs (`tutor/`, `rag/`, app READMEs) — note RAG is the mandatory default and
  the fail-closed behavior.

No route/JS/DB changes are required for Spec 1.

## Rollback / escape hatch

`TUTOR_CONTEXT_MODE=full_context` forces the historical full-context behavior
deploy-wide, bypassing RAG and the fail-closed path entirely.
