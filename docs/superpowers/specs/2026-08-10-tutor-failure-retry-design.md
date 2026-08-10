# Surface tutor failures as "Tap to retry", not a canned answer

**Date:** 2026-08-10
**Status:** Approved design, pending implementation plan
**Apps in scope:** `main_ui` and `sandbox_ui` (shared bridge + `run_tutor`)

## Problem

When the tutor's model output cannot be parsed into the strict
`{pedagogical-reasoning, Student-facing-answer}` JSON envelope,
`_normalize_tutor_ai_message` substitutes a canned answer:

> "I could not generate a valid response. Please restate your last message in
> one or two sentences so I can help."

This canned text is emitted as a normal `done` reply (and streamed as visible
deltas), so the chat route cannot distinguish success from failure. The student
sees the canned text rendered as an ordinary tutor **bubble**, complete with a
thumbs-up/down rating row and **no retry affordance**.

Genuine failures already behave correctly: an exception or an empty reply makes
the route emit an SSE `error` frame, and the frontend's `markTurnFailed()`
removes the tutor bubble, shows a red **"Tap to retry"** under the student
message, and shows the bottom banner **"Something went wrong, please try
again"**. The canned-fallback case is the one gap.

## Goal

Any tutor turn that fails to produce a valid answer should present the **same
failure UX as other failures**: no tutor bubble, a "Tap to retry" affordance,
and the existing bottom notification. The canned "I could not generate a valid
response" text must no longer appear as a chat bubble.

## Decisions (from brainstorming)

- **Failure UX:** the canned message is *not* a bubble. The failure surfaces as
  the bottom notification plus "Tap to retry".
- **Notification text:** keep the existing generic banner "Something went wrong,
  please try again" (no new copy, no frontend change).
- **Scope:** both `main_ui` and `sandbox_ui`.

## Approach (chosen)

A `failed` flag propagated from the tutor bridge, keyed off a shared sentinel
constant. Server-side only; no frontend, DB, or schema changes.

### 1. `tutor/run_tutor.py`
- Promote the canned answer string to a module-level constant
  `INVALID_RESPONSE_ANSWER` and use it inside `_normalize_tutor_ai_message`
  (single source of truth).
- In the three streaming sites that yield the visible answer as deltas, **do not
  yield the canned answer as a delta** — guard each with
  `if answer and answer != INVALID_RESPONSE_ANSWER`. This prevents a flash of the
  fake bubble before it is replaced by the retry state, and keeps the route's
  accumulated `full_reply` empty on failure.

### 2. `ui_core/tutor_bridge.py`
- In both `done` events (the cached-mode path and the non-cached path), compute:
  `failed = (not answer) or (answer == INVALID_RESPONSE_ANSWER)`
  and include `"failed": failed` in the yielded dict.
- `answer` is already available from `parse_tutor_response(full_raw)` at both
  sites.

### 3. `main_ui/routes/chat.py` and `sandbox_ui/routes/chat.py`
- Capture the flag from the `done` event: `failed = ev.get("failed")`.
- After the stream loop, replace the current `if not full_reply:` guard with a
  failure check that also honors the flag:
  `if not full_reply or failed:` → emit an `error` frame and `return` **before**
  `complete_exchange_tutor`, so no tutor row is persisted (identical to the
  existing empty-reply / exception paths). The student turn was already
  committed up front and is preserved for the retry.

### 4. Frontend
- No changes. `markTurnFailed()` in `main_ui/static/js/chat.js` (and the sandbox
  copy) already handles `error` frames exactly as desired.

## Rejected alternatives

- **(B) Metadata flag via `response_metadata`.** Have
  `_normalize_tutor_ai_message` stamp `response_metadata["tutor_failed"]`.
  Rejected: the `__done__` tuple's third element is a *separate* usage-bearing
  `AIMessage`, not the normalized message, so the flag would not ride along
  without extra plumbing.
- **(C) Detect the sentinel string in `chat.js`.** Rejected: fragile string
  match, duplicated across both apps, and it puts server-side truth in the
  client.

## Persistence & consumer impact

- On failure, no tutor `Message` row is written (matches today's error paths).
  The already-committed student row remains, so history stays coherent and the
  retry re-sends the same turn.
- The non-streaming `get_tutor_reply` and non-UI consumers (students runner,
  eval) are out of scope; they may continue to receive the canned text, which is
  harmless outside the chat UI.

## Testing (TDD)

- `ui_core/tutor_bridge` unit test: `done` event carries `failed=True` on a parse
  miss and on empty answer; `failed=False` on a valid answer.
- `tutor/run_tutor` test: an unparseable model output does **not** yield the
  canned answer as a visible delta (no delta emitted for the fallback).
- Route tests in **both** apps: a failed tutor turn yields an SSE `error` frame
  and persists **no** tutor row; a successful turn still yields `done` unchanged.

## Out of scope

- Changing the banner copy or adding a distinct "rephrase" hint.
- Retry/notification behavior for non-tutor failures (already handled).
- Any change to how the tutor decides validity (this only changes how an
  already-detected failure is surfaced).