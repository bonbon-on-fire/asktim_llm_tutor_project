# Caps, Limits & Forced Login — Design Spec

**Date:** 2026-07-27
**Status:** Approved (design), pending implementation plan
**Scope:** `main_ui` (production) only. `sandbox_ui` is the internal eval tool and is intentionally uncapped.

## Goal

Add cost-control + abuse guards to the production tutor:

1. A **per-message token cap** (unifies text + files + images into one budget).
2. A **per-conversation token ceiling** (hard block once cumulative usage crosses it).
3. **Forced login** after 3 messages per conversation, and before any file/image upload.

All limits are **hard blocks with a clear message** (the chosen enforcement style). Login uses the existing self-chosen **username + password** soft identity — sufficient for v1 (see Out of Scope).

## Locked parameters

| Limit | Value | Env override (in `main_ui/config.py`) |
|---|---|---|
| Per-message tokens | **10,000** | `MAX_MESSAGE_TOKENS` |
| Per-conversation tokens | **225,000** | `MAX_CONVERSATION_TOKENS` |
| Free messages before login | **3** | `FREE_MESSAGES_BEFORE_LOGIN` |

Chosen from real transcript data (108 conversations, 1,080 turns): 225k new tokens ≈ ~15 turns for a heavy/verbose conversation and ~25 for a typical one; 10k/message clears every legitimate message (worst legit ≈ 7k) while blocking a novel-length paste; a real student message is ~30 tokens (p50) / ~82 (max).

## Key facts that shape the design

- **No tokenizer in the repo.** Per-message tokens are *estimated* from size (~4 chars/token; images at a flat conservative per-image cost). Per-conversation tokens are read *post-hoc* from stored usage.
- **Attachments are already bounded.** `utils/attachments.py` truncates combined extracted file text to `MAX_EXTRACTED_CHARS = 15000` (~3,750 tokens) per message; images are capped at 3/message. The only unbounded input today is **typed text** (no `maxlength`, only a non-empty check).
- **Usage is stored post-hoc on tutor rows.** `messages.usage_json` holds the turn's cost dict: `{"usd": ..., "calls": {"tutor": {...}, "student": {...}, "embedding": {...}}}`, each call carrying `input_tokens`, `output_tokens`, `cache_read`. Written in `complete_exchange_tutor` from the bridge's `cost` event. There is currently a per-conversation **cost** sum but **no token** sum.
- **Login today is a pure nudge.** `read_username_cookie(request)` returns the signed username or None; nothing enforces it. `count_student_messages()` already exists.
- **The chat handler already returns JSON errors pre-stream** (`_bad_request` → 400, plus 403/404 helpers), then switches to SSE. All new gates run **pre-stream** and reuse that JSON-error path — no change to the streaming contract.

## Token accounting: what counts toward 225k

Per completed turn, sum over **every call** in `usage_json["calls"]`:

```
new_tokens(call) = max(0, input_tokens - cache_read) + output_tokens
turn_new_tokens  = sum(new_tokens(c) for c in calls.values())
```

The conversation total is the sum of `turn_new_tokens` over all its tutor rows. "New" (non-cached) tokens are used deliberately: they track actual spend, whereas raw `input_tokens` re-counts the ~18k cached system/course prefix every turn (cheap cache reads). Robust to missing keys (treat as 0) and to a null/malformed `usage_json` (treat that turn as 0).

Because this reads only *completed* turns, the ceiling trips on the **turn after** the one that crossed it (one-turn lag). The per-message cap is the real-time guard that prevents a single huge message from blowing far past the ceiling in one shot before the post-hoc counter reacts.

## Components & where each hooks in

### 1. Config — `main_ui/config.py`
Add three fields to the `Config` dataclass and read them in `load_config()` with the locked defaults:
```
max_message_tokens: int        = int(os.environ.get("MAX_MESSAGE_TOKENS", "10000"))
max_conversation_tokens: int   = int(os.environ.get("MAX_CONVERSATION_TOKENS", "225000"))
free_messages_before_login: int= int(os.environ.get("FREE_MESSAGES_BEFORE_LOGIN", "3"))
```

### 2. Token estimator — `utils/tokens.py` (new, pure)
```
CHARS_PER_TOKEN = 4
TOKENS_PER_IMAGE = 1600  # conservative flat per-image estimate (~Claude per-image max)

def estimate_message_tokens(text: str, extracted_texts: list[str], n_images: int) -> int:
    chars = len(text or "") + sum(len(t or "") for t in extracted_texts)
    return -(-chars // CHARS_PER_TOKEN) + n_images * TOKENS_PER_IMAGE   # ceil-div on chars
```
Pure, no Flask/DB — unit-testable in isolation, and reusable by the client mirror's contract (same constants).

### 3. Per-conversation token sum — `ui_core/services/conversation.py`
New `sum_conversation_new_tokens(db, conversation, *, models) -> int`, mirroring the existing cost-sum: query the conversation's tutor rows, parse each `usage_json`, sum `turn_new_tokens` per the formula above. Thin main_ui wrapper in `main_ui/services/conversation.py` (like `count_student_messages`). Also fix the stale docstring at `count_student_messages` ("Step 7's username modal triggers when this reaches 3").

### 4. Chat handler gates — `main_ui/routes/chat.py`
Move `username = read_username_cookie(request)` up so gates can see it, then insert these **pre-stream** checks in order (cheapest first; each returns the existing JSON-error shape):

1. **Per-message token cap** — after `enforce_combined_cap` (uploads validated, text known), no DB needed:
   `est = estimate_message_tokens(text, [a.extracted_text for a in attachments], len(images))`
   if `est >= config.max_message_tokens` → `400 {"error":"message_too_long","reason":..., "limit":..., "estimated":...}`.
2. **Upload requires login** — if `(images or attachments) and not username` → `403 {"error":"login_required","trigger":"attachment"}`.
3. *(find_or_create_conversation)* — unchanged.
4. **Message-count login gate** — `prior = count_student_messages(db, convo)`; if `not username and prior >= config.free_messages_before_login` → `403 {"error":"login_required","trigger":"message_count"}`. (First 3 student messages free; the 4th is blocked.)
5. **Conversation token ceiling** — `total = sum_conversation_new_tokens(db, convo)`; if `total >= config.max_conversation_tokens` → `403 {"error":"conversation_limit","reason":..., "used":total, "limit":...}`.

All five run before `start_exchange_student_only`, so a blocked turn writes nothing. Use `_abort_with` for gates 4–5 (session already owned).

**`done` event additions** (proactive client UX): after the tutor row commits, include
`"conversation_tokens": <total incl. this turn>` and `"conversation_limit_reached": <bool>`.
`student_message_count` is already present and drives the login modal.

### 5. Client mirror — `main_ui/static/js/chat.js`
- **Per-message:** mirror `CHARS_PER_TOKEN` / `TOKENS_PER_IMAGE` / `MAX_MESSAGE_TOKENS`; live-estimate on text/attachment change; disable send + inline "message too long — shorten it" when over. Preserve composer contents.
- **Forced login:** when `student_message_count >= 3` (from `done`) or the user attaches a file/image while logged out, show the existing username modal in **mandatory** (non-dismissible) mode and block send until a username cookie is set. Replaces the current nudge (`maybeShowEmailModal`).
- **Conversation limit:** when `conversation_limit_reached`, disable the composer and show "This chat reached its length limit — start a new chat."
- **Server errors are authority:** handle `message_too_long`, `login_required`, `conversation_limit` returned on send as the fallback (client estimate can lag).

## UX copy (hard blocks, composer preserved)

| Trigger | Message |
|---|---|
| Per-message over | "That message is too long. Shorten it or split it across turns." |
| Upload while logged out | "Log in to attach files or images." (opens modal) |
| 4th message logged out | "Log in to keep chatting." (opens modal, non-dismissible) |
| Conversation ceiling | "This chat reached its length limit — start a new chat to continue." |

## Testing

- **`utils/tokens.py`** — unit tests: text-only, files-only, images-only, mixed, empty; ceil-div boundary; a maxed legit message stays < 10k and a 50k-char paste exceeds it.
- **`sum_conversation_new_tokens`** — standalone sqlite-in-memory test (pattern of `main_ui/services/test_conversation_labels.py`): insert tutor rows with crafted `usage_json` (with `cache_read`), assert the summed new-token total; assert null/malformed `usage_json` counts as 0.
- **Handler gates** — Flask test client with `tutor_bridge.stream_tutor_reply` monkeypatched (no real LLM): assert 400 `message_too_long`; 403 `login_required` on upload-while-logged-out and on the 4th logged-out message (and that message 3 is allowed); 403 `conversation_limit` once a seeded conversation is over 225k; and that a normal turn still streams.

## Out of scope (v1)

- **Verified identity** (email confirmation / SSO). v1 ties usage to a self-chosen handle — deters casual overuse, not a determined user registering fresh handles.
- **Per-session / cross-conversation limits** (starting a new chat resets the per-conversation counters). Tier 3.
- **Rate limiting, global per-user daily budgets, tokenizer-based proactive pre-counting.** Tier 2/3.
- **`sandbox_ui`** — internal tool, uncapped.
