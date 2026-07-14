# Estimated cost per message (sandbox) — Design

**Date:** 2026-07-14
**Status:** Approved design, ready for implementation planning
**Scope:** Surface a trustable estimated USD cost for each tutor turn in the sandbox UI, and a running conversation total. Persist the cost for both `main_ui` and `sandbox_ui`; render it only in `sandbox_ui`.

## Goal

For every tutor reply in the sandbox, show how much that reply cost to produce, and a running total for the conversation. The number must be **accurate and auditable**: it is computed from the model's real reported token usage (input / output / prompt-cache reads / prompt-cache writes) plus the RAG query-embedding call when RAG is active, priced with the already-verified rate table in `utils/pricing.py`.

Non-goals: showing cost in `main_ui` (it persists but does not render); billing or quota enforcement; historical backfill of cost for messages created before this feature.

## Why this is low-risk

All pricing primitives already exist and are verified against published rates (2026-07):

- `utils/pricing.py::usage_from_message` — normalizes a LangChain message's `usage_metadata` into `{input_tokens, output_tokens, cache_read, cache_write}`, correctly summing Anthropic's per-TTL cache-write breakout.
- `utils/pricing.py::estimate_cost_usd` — cache-aware USD from token counts (cache-read 0.1×, cache-write 1.25× for the 5-minute ephemeral cache the tutor uses).
- `utils/pricing.py::model_from_message` — reads the *actual* model id from `response_metadata` (so a gpt-vs-claude mismatch cannot misprice).
- `utils/pricing.py::priced` — bundles usage + model + USD + a `rate_is_placeholder` flag.

Rate rows exist for `claude-sonnet-5`, `claude-sonnet-4-6`, `gpt-5.4`, and `text-embedding-3-small`. This feature adds **no new pricing logic** — only plumbing to carry usage from the model call to the DB and the UI.

## Data flow today (established by exploration)

- **Streaming (the live sandbox path):** `tutor/run_tutor.py::stream_tutor_reply` sets `stream_usage=True` on both providers and, at the end, builds a `normalized` `AIMessage` carrying `usage_metadata` + `response_metadata` (`run_tutor.py:815-821`). It then yields the terminal event `("__done__", normalized_text)` (`:832`) — **usage is dropped here.** The only consumer is `ui_core/tutor_bridge.py::stream_tutor_reply` (`:455-457`), whose `done` dict (`:466`) also omits usage.
- **Non-streaming:** `ui_core/tutor_bridge.py::get_tutor_reply` holds the final `AIMessage` as `out_messages[-1]` (`:405-412`) but returns `{reply, reasoning, retrieved}` (`:414`) — usage present, not exposed.
- **RAG embedding:** every `context_mode == "rag"` turn calls `retrieve_scored(course, query, …)` (`tutor_bridge.py:248`) → `embed_query` → `embed_texts` → `client.embeddings.create(model="text-embedding-3-small", …)` (`rag/embeddings.py:37`). The response's `usage` is **discarded**; the offline runner estimates `len(query)/4` instead.
- **Persistence:** `Message` (shared `MessageMixin` in `ui_core/db/models_common.py:67-120`, plus sandbox-only `retrieved_context`) has **no** cost/usage column. The tutor row is inserted by `complete_exchange_tutor` → shared `ui_core/services/conversation.py:157-179`. Model id is **not** persisted anywhere — only the abstract `Conversation.provider` (`"claude" | "gpt" | NULL`).
- **Cost is surfaced nowhere in any UI today** — only in offline runners (`internal_testing/run_transcript_rag.py`, `eval/tutor_judge/*`).

## Design

Five layers, from the model call outward.

### Layer 1 — Capture tutor usage (fix the streaming drop)

`tutor/run_tutor.py::stream_tutor_reply`: widen the terminal event from
`("__done__", normalized_text)` to `("__done__", normalized_text, normalized)`
so the usage-bearing `AIMessage` crosses the boundary. Update the single consumer
in `ui_core/tutor_bridge.py::stream_tutor_reply` (`:455-457`) to read the third
element (tolerating a 2-tuple for safety). The non-streaming path already has the
message as `out_messages[-1]`.

**Backward-compat note:** grep confirms the streaming terminal tuple is consumed
only by the bridge. The implementation must re-verify no other consumer (offline
runners use the non-streaming `get_tutor_reply`).

### Layer 2 — Assemble the price (bridge, centralized)

New private helper in `ui_core/tutor_bridge.py`:

```
_cost_for_turn(tutor_msg, *, provider, embedding_usage) -> dict
```

- `model = model_from_message(tutor_msg, fallback_for(provider))`
- `tutor = priced(model, usage_from_message(tutor_msg))`
- `embedding = priced("text-embedding-3-small", {"input_tokens": embedding_usage})` — only when RAG ran and `embedding_usage > 0`; else omitted.
- Returns `{"model": model, "usd": round(tutor_usd + embedding_usd, 6), "tutor": tutor, "embedding": embedding_or_None}`.

`fallback_for(provider)` mirrors the offline runner: `claude` → `ANTHROPIC_MODEL` env or `claude-sonnet-5`; else `OPENAI_MODEL` env or `gpt-5.4`. The fallback is only used if `response_metadata` lacks a model id.

Wire the returned dict onto:
- the streaming `done` dict (`tutor_bridge.py:466`) as `"cost"`,
- the non-streaming `get_tutor_reply` return (`:414`) as `"cost"`.

### Layer 3 — Exact RAG embedding tokens

Thread the real embedding token count instead of estimating:

- `rag/embeddings.py`: capture `resp.usage.prompt_tokens` (or `.total_tokens`) from `client.embeddings.create(...)`. Add a usage-returning entry point (e.g. `embed_query_with_usage(query) -> (vector, prompt_tokens)`) so existing `embed_query` / `embed_texts` callers are untouched. Default to `0` when the provider omits usage.
- `rag/retrieve.py::retrieve_scored`: return the query-embedding token count alongside the scored results (additive; keep the existing return shape working for other callers, or return a small result object — implementation plan decides the least-invasive form).
- `ui_core/tutor_bridge.py::_retrieved_context` / `retrieved_context`: capture that token count and pass it to `_cost_for_turn` as `embedding_usage`. Non-RAG turns pass `0`.

Embedding cost is tiny ($0.02 / 1M tokens) but is counted exactly for trust rather than estimated.

### Layer 4 — Persist (both apps)

Add two nullable columns to the shared `MessageMixin` (`ui_core/db/models_common.py`):

- `cost_usd` — numeric (store as `Float`/`Numeric`; nullable). The per-message estimated USD. `NULL` for pre-feature rows and for student rows.
- `usage_json` — `Text`, nullable. JSON string of the full breakdown returned by `_cost_for_turn` (`model`, tutor usage, embedding usage). This is what makes `cost_usd` **auditable** — any stored dollar figure can be re-derived from its token counts and the rate table.

Only the tutor row carries these. Set them in the shared insert `ui_core/services/conversation.py::complete_exchange_tutor` (extend its signature with `cost_usd` / `usage_json`), plumbed from both routes:
- `sandbox_ui/routes/chat.py` (SSE generator, tutor insert ~`:397-406`)
- `main_ui` equivalent tutor insert.

Both routes now have the `cost` dict from the bridge's `done` event, so both persist it.

Live-DB migration: add the two columns to the `_reconcile_columns()` / column-add pattern in **both** `sandbox_ui/run_app.py` and `main_ui/run_app.py`, so existing SQLite DBs gain the columns on startup (same mechanism used for prior sandbox columns).

### Layer 5 — Surface (sandbox only)

**Conversation total** — `SUM(cost_usd)` over the conversation's tutor rows, exposed as `total_cost_usd` in the shared conversation summary (`ui_core/services/conversation.py::_summarize_conversation`, which already runs per-conversation count/snippet queries). Both apps' summaries carry it; only the sandbox renders it.

- Sandbox sidebar entry header (`sandbox_ui/static/js/chat.js::formatEntryHeader`) appends the total:
  `Exercise 7 · Jul 14 · 2 messages · $0.04`
  Rendered only when `total_cost_usd` is present and > 0.

**Per-message** — model + cost under each tutor bubble:
`gpt-5.4 ($0.0075)`

- Live: the sandbox SSE `done` frame (`sandbox_ui/routes/chat.py` ~`:420-434`) gains `cost_usd` and `model` (from the bridge `cost` dict); `chat.js` renders the line under the just-streamed tutor bubble.
- History: the sandbox conversation-detail endpoint (`ui_core/web/blueprints/history.py::conversation_detail`, wired via `sandbox_ui/routes/history.py`) returns `cost_usd` and `model` per tutor message (model parsed from `usage_json`); `chat.js` renders it on reload.
- `main_ui` frontend is untouched — it stores the columns but never reads or renders them.

**Display formatting (JS helpers):**
- Per-message: `` `${model} ($${cost.toFixed(4)})` `` → `gpt-5.4 ($0.0075)`.
- Conversation total: 2 decimals, with a 4-decimal fallback when the total is below `$0.01` (so a cheap conversation still shows a non-zero figure): `· $0.04`, or `· $0.0072` when under a cent.

**CSS:** a small, muted line (reuse the muted-caption styling used elsewhere in the sandbox chat), placed under the tutor bubble; the total inherits the existing `sidebar-entry-title` styling.

## Edge cases & trust guarantees

- **Missing usage** (sanitized fallback message, provider omitted `usage_metadata`): `usage_from_message` returns zeros, `estimate_cost_usd` returns `0.0`, the row stores `cost_usd = 0.0`, and the UI shows `$0.0000`. No crash.
- **Non-RAG turn:** no embedding line; `embedding_usage = 0`.
- **Provider correctness:** cost uses the model id reported by the response, not the stored abstract `provider`, so an env override (`ANTHROPIC_MODEL` / `OPENAI_MODEL`) or a future model swap is priced correctly.
- **Unknown/placeholder rate:** `priced` sets `rate_is_placeholder`; today all live models have verified rates, so this stays `false`. Stored in `usage_json` for auditing.
- **Pre-feature messages:** `cost_usd` is `NULL`; the sidebar total sums only non-null rows; per-message line is omitted when `cost_usd` is `NULL`.
- **Auditability:** because `usage_json` stores the token breakdown and model id, any displayed dollar amount can be recomputed offline from `utils/pricing.py` and checked.

## Files touched (summary)

- `tutor/run_tutor.py` — widen streaming terminal event to carry the usage-bearing message.
- `ui_core/tutor_bridge.py` — `_cost_for_turn` helper; expose `cost` on streaming `done` and non-streaming return; capture embedding tokens.
- `rag/embeddings.py`, `rag/retrieve.py` — thread exact embedding token usage.
- `ui_core/db/models_common.py` — `cost_usd`, `usage_json` columns on `MessageMixin`.
- `ui_core/services/conversation.py` — persist cost on the tutor insert; add `total_cost_usd` to the conversation summary.
- `sandbox_ui/routes/chat.py`, `main_ui` route — pass the cost dict into the tutor insert.
- `sandbox_ui/run_app.py`, `main_ui/run_app.py` — live-DB column reconcile.
- `sandbox_ui/routes/history.py` / `ui_core/web/blueprints/history.py` — per-message `cost_usd` + `model` in detail payload (sandbox path).
- `sandbox_ui/static/js/chat.js`, `sandbox_ui/static/css/*` — render per-message line and sidebar total.

## Testing

- **Unit (pricing already covered):** add a bridge-level test that a fake tutor `AIMessage` with known `usage_metadata` + `response_metadata` produces the expected `cost` dict (tutor-only and tutor+embedding cases).
- **RAG embedding:** test that `retrieve_scored` surfaces a non-zero token count and that a non-RAG turn yields `0`.
- **Persistence:** test that `complete_exchange_tutor` writes `cost_usd` + `usage_json`, and that the conversation summary returns the correct `total_cost_usd` sum.
- **Serving:** existing sandbox history tests keep passing; extend one to assert `total_cost_usd` and per-message `cost_usd`/`model` appear in the payloads.
- **End-to-end:** drive a sandbox turn (per the verify skill) and confirm the per-message line and sidebar total render and match the stored values.
