# Cache-friendly Tutor History Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Interleave each turn's RAG as a system message after its student turn and replay the verbatim full tutor JSON, so the whole conversation history caches turn-to-turn — gated by a single global env flag, default off.

**Architecture:** A provider-neutral builder turns stored history rows into an interleaved message list (`system(static) → student → system(rag) → tutor(rawJSON) → …`). The Claude cached path sends it via the **raw `anthropic` SDK** (langchain rejects multiple non-consecutive system messages); the GPT cached path uses langchain (which accepts it). A single global env flag `TUTOR_CACHED_HISTORY` (truthy = on, default off) selects cached vs. today's legacy path at send time. This is throwaway validation scaffolding: prove caching is cheaper, then either flip it fully on or remove the legacy path. Legacy path is untouched.

**Tech Stack:** Python 3.12, Flask, SQLAlchemy, Alembic (main_ui) / boot `_reconcile_columns` (sandbox), `langchain_openai` / `langchain_anthropic`, raw `anthropic` SDK (0.105.2), `pytest`.

## Global Constraints

- **Domain roles are student / tutor / system.** API-role mapping: student → `user`, tutor → `assistant`, system → `system`.
- **Default off:** `TUTOR_CACHED_HISTORY` is unset/falsey by default — every turn uses the legacy path; CI and existing tests stay on the legacy path unchanged. Truthy values: `1`, `true`, `yes`, `on` (case-insensitive).
- **Byte-stability is the whole point:** every replayed `rag_k` and `tutor_k` block MUST be identical across turns of a conversation, or caching misses. Reconstruct from stored data deterministically (fixed JSON key order, `ensure_ascii=False`).
- **Fail-closed retrieval unchanged:** in `rag` context mode, empty current-turn retrieval still raises `RagUnavailableError` before any model call.
- **No Claude co-author trailer** in commits (repo convention).
- **Legacy path must not change behavior** — only add the cached branch alongside it.
- **No per-conversation mode column.** Gating is a single process-wide env flag; there is no `history_mode` column and no per-conversation A/B assignment. main_ui persists per-turn RAG unconditionally (harmless when the flag is off), so a conversation started while the flag is on has replayable RAG from turn 1.

---

## File Structure

- `tutor/cached_history.py` **(new)** — provider-neutral: canonical tutor-JSON reconstruction + interleaved message-list builder (list of `(role, content)` steps). One responsibility: turn history data into the ordered message plan.
- `tutor/run_tutor.py` **(modify)** — add `stream_tutor_reply_anthropic_raw(...)` (raw-SDK streaming sender that drives `StudentAnswerExtractor`), and `build_anthropic_request(...)` (convert the neutral plan → anthropic `system` + `messages` with cache_control breakpoints).
- `ui_core/tutor_bridge.py` **(modify)** — add `cached_history_enabled()` env-gate helper; in `stream_tutor_reply`, branch on `history_mode`: cached → build interleaved plan and dispatch to the raw-Anthropic sender (Claude) or a langchain interleaved sender (GPT); legacy → today's path.
- `ui_core/services/conversation.py` **(modify)** — `get_cached_history_for_tutor(...)` returning per-turn `{student_content, rag_text, tutor_json}`; make `complete_exchange_tutor` accept `retrieved_context`.
- `main_ui/db/models.py` **(modify)** + new Alembic migration — add `retrieved_context` column to `Message`.
- `main_ui/routes/chat.py`, `sandbox_ui/routes/chat.py` **(modify)** — persist `rc.records` (main_ui); read the env flag and thread `history_mode` + cached history into `stream_kwargs`.
- `main_ui/services/conversation.py`, `sandbox_ui/services/conversation.py` **(modify)** — thin wrappers for `get_cached_history_for_tutor` + `complete_exchange_tutor(retrieved_context=...)` (main_ui).
- `tutor/test_cached_history.py`, `ui_core/test_cached_history_bridge.py` **(new tests)**.

---

## Task 1: Canonical tutor-JSON + interleaved message builder

**Files:**
- Create: `tutor/cached_history.py`
- Test: `tutor/test_cached_history.py`

**Interfaces:**
- Produces:
  - `tutor_output_json(reasoning: str | None, answer: str | None) -> str` — canonical `{"pedagogical-reasoning": ..., "Student-facing-answer": ...}` string (fixed key order, `ensure_ascii=False`).
  - `build_message_plan(*, static_system: str, prior_turns: list[dict], current_student: str, current_rag: str) -> list[tuple[str, str]]` — ordered `(role, content)` steps where role ∈ `{"system_static","student","rag","tutor"}`. `prior_turns` items are `{"student_content": str, "rag_text": str, "tutor_json": str}`. `current_rag` may be `""` (non-rag mode → no trailing rag step).

- [ ] **Step 1: Write the failing tests**

```python
# tutor/test_cached_history.py
from tutor.cached_history import tutor_output_json, build_message_plan


def test_tutor_output_json_is_canonical_and_stable():
    a = tutor_output_json("reasoned", "answer")
    b = tutor_output_json("reasoned", "answer")
    assert a == b  # byte-stable
    assert a == '{"pedagogical-reasoning": "reasoned", "Student-facing-answer": "answer"}'
    # None coerces to empty string, never null
    assert tutor_output_json(None, "x") == '{"pedagogical-reasoning": "", "Student-facing-answer": "x"}'


def test_build_message_plan_interleaves_rag_after_student():
    plan = build_message_plan(
        static_system="SYS",
        prior_turns=[
            {"student_content": "s1", "rag_text": "r1", "tutor_json": "t1"},
            {"student_content": "s2", "rag_text": "r2", "tutor_json": "t2"},
        ],
        current_student="s3",
        current_rag="r3",
    )
    assert plan == [
        ("system_static", "SYS"),
        ("student", "s1"), ("rag", "r1"), ("tutor", "t1"),
        ("student", "s2"), ("rag", "r2"), ("tutor", "t2"),
        ("student", "s3"), ("rag", "r3"),
    ]


def test_build_message_plan_omits_empty_current_rag():
    plan = build_message_plan(static_system="SYS", prior_turns=[], current_student="s1", current_rag="")
    assert plan == [("system_static", "SYS"), ("student", "s1")]


def test_build_message_plan_omits_empty_prior_rag():
    plan = build_message_plan(
        static_system="SYS",
        prior_turns=[{"student_content": "s1", "rag_text": "", "tutor_json": "t1"}],
        current_student="s2",
        current_rag="r2",
    )
    assert plan == [("system_static", "SYS"), ("student", "s1"), ("tutor", "t1"), ("student", "s2"), ("rag", "r2")]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=. python -m pytest tutor/test_cached_history.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tutor.cached_history'`

- [ ] **Step 3: Write the implementation**

```python
# tutor/cached_history.py
"""Provider-neutral assembly of the cache-friendly interleaved message plan.

The plan is a list of (role, content) steps that each provider sender converts
to its own message shape. Roles: 'system_static' (leading system prompt),
'student', 'rag' (a system-channel retrieval block), 'tutor' (verbatim JSON).

Byte-stability matters: every replayed rag/tutor block must be identical across
turns of a conversation or prompt caching misses. tutor_output_json produces a
canonical, deterministic string from the two stored fields.
"""
from __future__ import annotations

import json


def tutor_output_json(reasoning: str | None, answer: str | None) -> str:
    """Canonical verbatim tutor output: the two-field JSON, fixed key order."""
    return json.dumps(
        {
            "pedagogical-reasoning": reasoning or "",
            "Student-facing-answer": answer or "",
        },
        ensure_ascii=False,
    )


def build_message_plan(
    *,
    static_system: str,
    prior_turns: list[dict],
    current_student: str,
    current_rag: str,
) -> list[tuple[str, str]]:
    """Ordered (role, content) plan: system, then per prior turn
    student -> [rag] -> tutor, then the current student -> [rag]. RAG steps with
    empty text are omitted (non-rag mode / no retrieval)."""
    plan: list[tuple[str, str]] = [("system_static", static_system)]
    for t in prior_turns:
        plan.append(("student", t["student_content"]))
        if t.get("rag_text"):
            plan.append(("rag", t["rag_text"]))
        plan.append(("tutor", t["tutor_json"]))
    plan.append(("student", current_student))
    if current_rag:
        plan.append(("rag", current_rag))
    return plan
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=. python -m pytest tutor/test_cached_history.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add tutor/cached_history.py tutor/test_cached_history.py
git commit -m "feat(tutor): interleaved message-plan builder + canonical tutor JSON"
```

---

## Task 2: Raw-Anthropic streaming sender

**Files:**
- Modify: `tutor/run_tutor.py` (add two functions near `stream_tutor_reply`)
- Test: `tutor/test_cached_history.py` (add request-shape test; the stream itself is covered by the live smoke in Task 7)

**Interfaces:**
- Consumes: `build_message_plan` output (Task 1); `StudentAnswerExtractor`, `parse_tutor_response`, `_normalize_tutor_ai_message`, `_sanitize_text_for_transport` (existing in `run_tutor.py`).
- Produces:
  - `build_anthropic_request(plan: list[tuple[str,str]]) -> tuple[list[dict], list[dict]]` — returns `(system_blocks, messages)` for `anthropic.Anthropic().messages.stream(...)`. `system_blocks` is the static prompt as one cache-marked text block. `messages` interleaves `{"role":"user"|"assistant"|"system", "content": ...}` with cache_control breakpoints on the last block and every ~15th block.
  - `stream_tutor_reply_anthropic_raw(plan, *, model_name, api_key) -> Iterator` — yields visible answer `str` chunks, then `("__done__", raw_json)` (same contract as the existing `stream_tutor_reply`).

- [ ] **Step 1: Write the failing test**

```python
# add to tutor/test_cached_history.py
from tutor.run_tutor import build_anthropic_request


def test_build_anthropic_request_shapes_roles_and_caches_static():
    plan = [
        ("system_static", "SYS"),
        ("student", "s1"), ("rag", "r1"), ("tutor", "t1"),
        ("student", "s2"), ("rag", "r2"),
    ]
    system_blocks, messages = build_anthropic_request(plan)
    # static system is one cache-marked block
    assert system_blocks == [{"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}]
    # roles map: student->user, tutor->assistant, rag->system
    assert [m["role"] for m in messages] == ["user", "system", "assistant", "user", "system"]
    assert messages[0]["content"] == "s1" and messages[1]["content"] == "r1"
    # last message carries a cache breakpoint (as a content block)
    last = messages[-1]
    assert isinstance(last["content"], list) and last["content"][-1]["cache_control"] == {"type": "ephemeral"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=. python -m pytest tutor/test_cached_history.py::test_build_anthropic_request_shapes_roles_and_caches_static -v`
Expected: FAIL with `ImportError: cannot import name 'build_anthropic_request'`

- [ ] **Step 3: Write the implementation**

Add to `tutor/run_tutor.py` (after `stream_tutor_reply`). Note: `import anthropic` at module top alongside the existing imports.

```python
_ROLE_MAP = {"student": "user", "tutor": "assistant", "rag": "system"}
_CACHE_EVERY = 15  # keep the incremental read within Anthropic's 20-block lookback


def build_anthropic_request(plan):
    """Convert a (role, content) plan into (system_blocks, messages) for the raw
    anthropic Messages API. Static system is a cache-marked text block; a
    cache_control breakpoint is placed on the last message block and every
    _CACHE_EVERY-th message block (<= 4 breakpoints for realistic lengths)."""
    static = ""
    steps = []
    for role, content in plan:
        if role == "system_static":
            static = content
        else:
            steps.append((_ROLE_MAP[role], _sanitize_text_for_transport(content)))
    system_blocks = [{"type": "text", "text": _sanitize_text_for_transport(static),
                      "cache_control": {"type": "ephemeral"}}]
    n = len(steps)
    messages = []
    for i, (role, content) in enumerate(steps):
        mark = (i == n - 1) or (i % _CACHE_EVERY == _CACHE_EVERY - 1)
        if mark:
            messages.append({"role": role,
                             "content": [{"type": "text", "text": content,
                                          "cache_control": {"type": "ephemeral"}}]})
        else:
            messages.append({"role": role, "content": content})
    return system_blocks, messages


def stream_tutor_reply_anthropic_raw(plan, *, model_name, api_key):
    """Stream a cached-mode tutor reply via the raw anthropic SDK (langchain
    rejects the interleaved multi-system structure). Same yield contract as
    stream_tutor_reply: visible str chunks, then ('__done__', normalized_json)."""
    system_blocks, messages = build_anthropic_request(plan)
    client = anthropic.Anthropic(api_key=api_key)
    extractor = StudentAnswerExtractor()
    with client.messages.stream(
        model=model_name, max_tokens=8192, system=system_blocks, messages=messages,
    ) as stream:
        for text in stream.text_stream:
            visible = extractor.feed(text)
            if visible:
                yield visible
    raw = extractor.buffer
    normalized = _normalize_tutor_ai_message(AIMessage(content=raw))
    normalized_text = normalized.content if isinstance(normalized.content, str) else str(normalized.content)
    if not extractor.found_answer:
        _, answer = parse_tutor_response(normalized_text)
        if answer:
            yield answer
    yield ("__done__", normalized_text)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `PYTHONPATH=. python -m pytest tutor/test_cached_history.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add tutor/run_tutor.py tutor/test_cached_history.py
git commit -m "feat(tutor): raw-anthropic interleaved streaming sender for cached mode"
```

---

## Task 3: main_ui DB column (`retrieved_context`) + migration

**Files:**
- Modify: `main_ui/db/models.py` (add one column)
- Create: `main_ui/db/migrations/versions/<newrev>_add_retrieved_context.py`

**Interfaces:**
- Produces: `Message.retrieved_context: str | None` on main_ui. (sandbox `Message` already has this column.)

- [ ] **Step 1: Confirm the current Alembic head**

Run: `PYTHONPATH=. python -m alembic -c main_ui/db/migrations/alembic.ini heads` (or read the newest file's `revision`). At authoring time the head is `a1b2c3d4e5f6`; **use whatever the actual head is** as `down_revision` (a concurrent migration may have landed first).

- [ ] **Step 2: Add the column to the model**

In `main_ui/db/models.py`, in `class Message(MessageMixin, Base)` add:
```python
    # Cached-history mode: JSON string of the RAG records retrieved for this
    # (tutor) turn, so past RAG can be replayed as a system message. NULL for
    # pre-feature rows and turns where no retrieval ran.
    retrieved_context: Mapped[str | None] = mapped_column(Text, nullable=True)
```
(Ensure `Text` is imported — it already is for other columns.)

- [ ] **Step 3: Write the migration**

Create `main_ui/db/migrations/versions/c9f1a2b3d4e5_add_retrieved_context.py`:
```python
"""add retrieved_context (messages)

Nullable; pre-feature rows stay NULL.

Revision ID: c9f1a2b3d4e5
Revises: a1b2c3d4e5f6
Create Date: 2026-07-14 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c9f1a2b3d4e5'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'  # use the real current head
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.add_column(sa.Column('retrieved_context', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.drop_column('retrieved_context')
```

- [ ] **Step 4: Run the migration against a scratch SQLite DB**

Run:
```bash
DATABASE_URL="sqlite:///./_scratch_mig.db" PYTHONPATH=. python -m alembic -c main_ui/db/migrations/alembic.ini upgrade head
```
Expected: no error; ends at revision `c9f1a2b3d4e5`. Then `rm _scratch_mig.db`.

- [ ] **Step 5: Commit**

```bash
git add main_ui/db/models.py main_ui/db/migrations/versions/c9f1a2b3d4e5_add_retrieved_context.py
git commit -m "feat(main_ui): add retrieved_context column to Message (+ migration)"
```

---

## Task 4: Persist per-turn RAG on main_ui + shared `complete_exchange_tutor`

**Files:**
- Modify: `ui_core/services/conversation.py` (`complete_exchange_tutor` accepts `retrieved_context`)
- Modify: `main_ui/services/conversation.py` (wrapper passes it through)
- Modify: `main_ui/routes/chat.py` (capture `ev.get("retrieved")`, pass to `complete_exchange_tutor`)
- Test: `ui_core/services/test_conversation.py`

**Interfaces:**
- Consumes: the SSE `done` event's `retrieved` records (already emitted by the bridge).
- Produces: `complete_exchange_tutor(..., retrieved_context: str | None = None)` sets `msg.retrieved_context` when the model's `Message` has that attribute (main_ui after Task 3; sandbox already does). Persists unconditionally — the flag does not gate storage.

- [ ] **Step 1: Write the failing test**

```python
# ui_core/services/test_conversation.py  (add a test using the existing fixtures)
def test_complete_exchange_tutor_persists_retrieved_context(session, models, conversation):
    from ui_core.services.conversation import start_exchange_student_only, complete_exchange_tutor
    s = start_exchange_student_only(session, models=models, conversation=conversation, student_text="q")
    complete_exchange_tutor(session, models=models, conversation=conversation, turn=s.turn,
                            tutor_text="a", pedagogical_reasoning="why",
                            retrieved_context='[{"source":"x"}]')
    session.flush()
    tutor_msg = [m for m in conversation.messages if m.role == "tutor"][-1]
    assert tutor_msg.retrieved_context == '[{"source":"x"}]'
```
(Mirror the fixture style already in `ui_core/services/test_conversation.py`. If those fixtures use sandbox models, that's fine — sandbox `Message` already has `retrieved_context`.)

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. python -m pytest ui_core/services/test_conversation.py::test_complete_exchange_tutor_persists_retrieved_context -v`
Expected: FAIL (`complete_exchange_tutor` has no `retrieved_context` kwarg, or the attribute isn't set)

- [ ] **Step 3: Implement**

In `ui_core/services/conversation.py`, `complete_exchange_tutor` signature: add `retrieved_context: str | None = None`. After building the tutor `Message`, before `db.flush()`:
```python
    if retrieved_context is not None and hasattr(tutor_msg, "retrieved_context"):
        tutor_msg.retrieved_context = retrieved_context
```
In `main_ui/services/conversation.py` `complete_exchange_tutor` wrapper: add `retrieved_context: str | None = None` param and pass `retrieved_context=retrieved_context` to `_shared.complete_exchange_tutor(...)`.
In `main_ui/routes/chat.py` `event_stream()`: capture retrieved like sandbox does — add `retrieved = None` near `reasoning = None`, set `retrieved = ev.get("retrieved") or None` in the `done` branch, and pass to the persist call:
```python
                tutor_msg = complete_exchange_tutor(
                    db, conversation=convo_obj, turn=student_turn,
                    tutor_text=full_reply, pedagogical_reasoning=reasoning,
                    retrieved_context=(json.dumps(retrieved, ensure_ascii=False) if retrieved else None),
                )
```
(Ensure `import json` is present in `main_ui/routes/chat.py` — it is.)

- [ ] **Step 4: Run to verify it passes + full conversation-service suite**

Run: `PYTHONPATH=. python -m pytest ui_core/services/test_conversation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ui_core/services/conversation.py main_ui/services/conversation.py main_ui/routes/chat.py ui_core/services/test_conversation.py
git commit -m "feat: persist per-turn RAG records on main_ui tutor turns"
```

---

## Task 5: Cached-mode history builder in the conversation service

**Files:**
- Modify: `ui_core/services/conversation.py` (`get_cached_history_for_tutor`)
- Modify: `main_ui/services/conversation.py`, `sandbox_ui/services/conversation.py` (wrappers)
- Test: `ui_core/services/test_conversation.py`

**Interfaces:**
- Produces: `get_cached_history_for_tutor(db, conversation, *, models) -> list[dict]` — one dict per prior **completed** turn: `{"student_content": str, "rag_text": str, "tutor_json": str}`, chronological. `rag_text` is the stored `retrieved_context` records re-rendered via `rag.retrieve.format_context` + the RAG header (empty string if none). `tutor_json` is `tutor_output_json(reasoning, answer)`. Student attachment text is re-injected into `student_content` (same as legacy `get_history_for_tutor`).

- [ ] **Step 1: Write the failing test**

```python
# ui_core/services/test_conversation.py
def test_cached_history_pairs_student_rag_tutor(session, models, conversation):
    from ui_core.services.conversation import complete_exchange_tutor, start_exchange_student_only, get_cached_history_for_tutor
    s = start_exchange_student_only(session, models=models, conversation=conversation, student_text="q1")
    complete_exchange_tutor(session, models=models, conversation=conversation, turn=s.turn,
                            tutor_text="a1", pedagogical_reasoning="why1",
                            retrieved_context='[{"source":"local:lecture_1_1_x","score":0.9,"chars":3,"text":"foo"}]')
    session.flush()
    rows = get_cached_history_for_tutor(session, conversation, models=models)
    assert len(rows) == 1
    assert rows[0]["student_content"] == "q1"
    assert '"pedagogical-reasoning": "why1"' in rows[0]["tutor_json"]
    assert "foo" in rows[0]["rag_text"]  # re-rendered RAG block
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. python -m pytest ui_core/services/test_conversation.py::test_cached_history_pairs_student_rag_tutor -v`
Expected: FAIL (`get_cached_history_for_tutor` undefined)

- [ ] **Step 3: Implement**

In `ui_core/services/conversation.py`:
```python
import json as _json
from rag.retrieve import format_context
from rag.chunking import Chunk
from tutor.cached_history import tutor_output_json
from ui_core.tutor_bridge import RETRIEVED_CONTEXT_HEADER  # or duplicate the header constant


def _rag_text_from_records(records_json: str | None, course: str) -> str:
    if not records_json:
        return ""
    try:
        records = _json.loads(records_json)
    except (ValueError, TypeError):
        return ""
    if not records:
        return ""
    chunks = [Chunk(source=r.get("source", ""), text=r.get("text", "")) for r in records]
    block = format_context(chunks, course)
    return f"{RETRIEVED_CONTEXT_HEADER}\n\n{block}" if block else ""


def get_cached_history_for_tutor(db, conversation, *, models):
    """Per prior completed turn: {student_content, rag_text, tutor_json}."""
    stmt = (select(models.Message)
            .where(models.Message.conversation_id == conversation.id)
            .order_by(models.Message.turn, models.Message.id))
    msgs = db.execute(stmt).scalars().all()
    files_by_message = _files_by_message(db, conversation, models=models)
    by_turn: dict[int, dict] = {}
    for m in msgs:
        slot = by_turn.setdefault(m.turn, {})
        if m.role == "student":
            slot["student_content"] = _content_with_attachments(m.content, files_by_message.get(m.id, []))
        elif m.role == "tutor":
            slot["tutor_json"] = tutor_output_json(m.pedagogical_reasoning, m.content)
            slot["rag_text"] = _rag_text_from_records(getattr(m, "retrieved_context", None), conversation.course)
    out = []
    for turn in sorted(by_turn):
        s = by_turn[turn]
        if "student_content" in s and "tutor_json" in s:  # only completed turns
            out.append({"student_content": s["student_content"], "rag_text": s.get("rag_text", ""), "tutor_json": s["tutor_json"]})
    return out
```
Add thin wrappers in `main_ui/services/conversation.py` and `sandbox_ui/services/conversation.py`:
```python
def get_cached_history_for_tutor(db, conversation):
    return _shared.get_cached_history_for_tutor(db, conversation, models=_MODELS)
```
**Note the import cycle risk:** `ui_core.services.conversation` importing `ui_core.tutor_bridge` for `RETRIEVED_CONTEXT_HEADER`. If that cycles, copy the header constant into a small shared module (`tutor/cached_history.py`) and import from there in both places.

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. python -m pytest ui_core/services/test_conversation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ui_core/services/conversation.py main_ui/services/conversation.py sandbox_ui/services/conversation.py ui_core/services/test_conversation.py
git commit -m "feat: cached-mode history builder (student + replayed RAG + verbatim tutor JSON)"
```

---

## Task 6: Bridge wiring — dispatch cached mode, gated by the env flag

**Files:**
- Modify: `ui_core/tutor_bridge.py` (`cached_history_enabled()` helper + `stream_tutor_reply` branch)
- Modify: `main_ui/routes/chat.py`, `sandbox_ui/routes/chat.py` (read the env flag; thread `history_mode` + cached history into `stream_kwargs`)
- Test: `ui_core/test_cached_history_bridge.py`

**Interfaces:**
- Consumes: `build_message_plan`, `stream_tutor_reply_anthropic_raw`, `build_tutor_model` (Tasks 1–2); `get_cached_history_for_tutor` (Task 5); the existing `retrieved_context`, `_get_or_build_stream_context`, `_enforce_rag_available`, `_retrieved_context_block`, `turn_attachments`.
- Produces:
  - `cached_history_enabled() -> bool` (module-level) — `True` iff `os.environ["TUTOR_CACHED_HISTORY"]` is truthy (`1`/`true`/`yes`/`on`, case-insensitive). Default off.
  - `stream_tutor_reply(..., history_mode: str = "legacy", cached_history: list[dict] | None = None, **ctx)` — when `history_mode == "cached"`, builds the interleaved plan and streams via the raw-Anthropic sender (Claude) or a langchain interleaved sender (GPT); otherwise the current legacy path (unchanged).

- [ ] **Step 1: Write the failing tests**

```python
# ui_core/test_cached_history_bridge.py
from unittest.mock import patch
from ui_core.tutor_bridge import TutorBridge, cached_history_enabled


def test_cached_history_enabled_defaults_off(monkeypatch):
    monkeypatch.delenv("TUTOR_CACHED_HISTORY", raising=False)
    assert cached_history_enabled() is False
    monkeypatch.setenv("TUTOR_CACHED_HISTORY", "on")
    assert cached_history_enabled() is True
    monkeypatch.setenv("TUTOR_CACHED_HISTORY", "0")
    assert cached_history_enabled() is False


def test_cached_gpt_builds_interleaved_messages():
    bridge = TutorBridge()
    captured = {}
    class FakeChunk:  # mimics langchain AIMessageChunk
        content = '{"pedagogical-reasoning":"r","Student-facing-answer":"hi"}'
    class FakeModel:
        def stream(self, messages, **kw):
            captured["messages"] = messages
            return iter([FakeChunk()])
    with patch.object(bridge, "_get_or_build_stream_context", return_value=(FakeModel(), "SYS")), \
         patch.object(bridge, "retrieved_context", return_value=type("RC", (), {"text": "RAGNOW", "records": [{"source":"x","text":"t"}]})()), \
         patch.object(bridge, "_enforce_rag_available"):
        list(bridge.stream_tutor_reply(
            course="c", exercise="1", tutor="tutor_07",
            history=[], new_student_message="hello",
            provider="gpt", history_mode="cached",
            cached_history=[{"student_content": "s1", "rag_text": "R1", "tutor_json": "T1"}],
        ))
    roles = [type(m).__name__ for m in captured["messages"]]
    # SystemMessage(static), Human(s1), System(R1), AI(T1), Human(hello), System(RAGNOW)
    assert roles == ["SystemMessage", "HumanMessage", "SystemMessage", "AIMessage", "HumanMessage", "SystemMessage"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. python -m pytest ui_core/test_cached_history_bridge.py -v`
Expected: FAIL (`cached_history_enabled` undefined / `stream_tutor_reply` has no `history_mode`/`cached_history` params)

- [ ] **Step 3: Implement**

In `ui_core/tutor_bridge.py`, imports at top:
```python
import os  # if not already imported
from tutor.cached_history import build_message_plan
from tutor.run_tutor import (
    stream_tutor_reply_anthropic_raw, StudentAnswerExtractor,
    _normalize_tutor_ai_message, parse_tutor_response, _require_anthropic_api_key,
)
from langchain_core.messages import SystemMessage
```
Module-level env gate:
```python
_TRUTHY = {"1", "true", "yes", "on"}


def cached_history_enabled() -> bool:
    """Global on/off for cache-friendly interleaved history. Default off."""
    return os.environ.get("TUTOR_CACHED_HISTORY", "").strip().lower() in _TRUTHY
```
Plan → langchain messages (GPT cached):
```python
    def _plan_to_langchain(self, plan):
        out = []
        for role, content in plan:
            if role in ("system_static", "rag"):
                out.append(SystemMessage(content=content))
            elif role == "student":
                out.append(HumanMessage(content=content))
            else:  # tutor
                out.append(AIMessage(content=content))
        return out
```
In `stream_tutor_reply`, add params `history_mode: str = "legacy"` and `cached_history: list[dict] | None = None`, and after `rc = self.retrieved_context(...)` + `self._enforce_rag_available(ctx, rc)` (unchanged), branch:
```python
        if history_mode == "cached":
            provider = _resolve_provider(ctx.get("provider"))
            _model, system_prompt = self._get_or_build_stream_context(tutor, course, exercise, **ctx)
            plan = build_message_plan(
                static_system=system_prompt,
                prior_turns=cached_history or [],
                current_student=new_student_message,
                current_rag=self._retrieved_context_block(rc.text),
            )
            full_raw = None
            if provider == "claude":
                model_name = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
                for item in stream_tutor_reply_anthropic_raw(
                    plan, model_name=model_name, api_key=_require_anthropic_api_key()
                ):
                    if isinstance(item, tuple) and item and item[0] == "__done__":
                        full_raw = item[1]; break
                    if isinstance(item, str) and item:
                        yield {"type": "delta", "text": item}
            else:  # gpt via langchain (accepts interleaved system messages)
                model = _model
                messages = self._plan_to_langchain(plan)
                extractor = StudentAnswerExtractor()
                for chunk in model.stream(messages):
                    piece = chunk.content if hasattr(chunk, "content") else str(chunk)
                    if not isinstance(piece, str):
                        piece = str(piece)
                    visible = extractor.feed(piece)
                    if visible:
                        yield {"type": "delta", "text": visible}
                raw = extractor.buffer
                full_raw = _normalize_tutor_ai_message(AIMessage(content=raw)).content
            reasoning, answer = (None, "")
            if full_raw:
                reasoning, answer = parse_tutor_response(full_raw)
            yield {"type": "done", "reply": answer or "", "reasoning": reasoning, "retrieved": rc.records}
            return
```
(`_resolve_provider`, `HumanMessage`, `AIMessage` are already imported in the bridge. Verify `parse_tutor_response` / `_normalize_tutor_ai_message` / `StudentAnswerExtractor` import names match `tutor/run_tutor.py`.)
Then thread it from both routes: after resolving the conversation, compute
```python
    stream_history_mode = "cached" if cached_history_enabled() else "legacy"
    cached_history = (
        conversation_service.get_cached_history_for_tutor(db, convo_obj)
        if stream_history_mode == "cached" else []
    )
```
and add `history_mode=stream_history_mode, cached_history=cached_history` to `stream_kwargs`. (Use each route's existing conversation-service import alias and conversation-object variable name; the two routes differ only in those names.) Do **not** thread anything through `find_or_create_conversation` — there is no per-conversation mode.

- [ ] **Step 4: Run to verify it passes + no legacy regression**

Run: `PYTHONPATH=. python -m pytest ui_core/test_cached_history_bridge.py ui_core/test_tutor_bridge.py tutor/ -v`
Expected: PASS (new tests + existing legacy tests still green)

- [ ] **Step 5: Commit**

```bash
git add ui_core/tutor_bridge.py main_ui/routes/chat.py sandbox_ui/routes/chat.py ui_core/test_cached_history_bridge.py
git commit -m "feat: dispatch cached-history interleaved streaming, gated by TUTOR_CACHED_HISTORY"
```

---

## Task 7: Live smoke — prove the history caches

**Files:**
- Create: `internal_testing/smoke_cached_history.py` (manual/live, not part of CI)

**Interfaces:**
- Consumes: the raw-Anthropic sender + `build_anthropic_request`; a real `ANTHROPIC_API_KEY`.

- [ ] **Step 1: Write the smoke script**

```python
# internal_testing/smoke_cached_history.py
"""Live proof that cached-mode history caches. Run manually with real keys:
    TUTOR_CACHED_HISTORY=1 PYTHONPATH=. python -m internal_testing.smoke_cached_history
Sends a 2-turn Claude conversation via the raw request builder and prints usage;
turn 2 should show cache_read_input_tokens > 0."""
import anthropic
from tutor.run_tutor import _require_anthropic_api_key, load_system_prompt, build_anthropic_request
from tutor.cached_history import build_message_plan, tutor_output_json

client = anthropic.Anthropic(api_key=_require_anthropic_api_key())
sysprompt = load_system_prompt("tutor_07", assignment_override="Exercise: intro.")

def run(plan, label):
    system_blocks, messages = build_anthropic_request(plan)
    r = client.messages.create(model="claude-sonnet-5", max_tokens=64, system=system_blocks, messages=messages)
    u = r.usage
    print(f"{label}: cache_read={getattr(u,'cache_read_input_tokens',0)} "
          f"cache_write={getattr(u,'cache_creation_input_tokens',0)} input={u.input_tokens}")

# Turn 1: writes the prefix to cache
plan1 = build_message_plan(static_system=sysprompt, prior_turns=[], current_student="what is a topic sentence?", current_rag="Retrieved: a topic sentence states the paragraph's main idea.")
run(plan1, "turn1")
# Turn 2: prior turn replayed verbatim -> should cache-READ the prefix
prior = [{"student_content": "what is a topic sentence?", "rag_text": "Retrieved: a topic sentence states the paragraph's main idea.", "tutor_json": tutor_output_json("think", "A topic sentence states the main idea.")}]
plan2 = build_message_plan(static_system=sysprompt, prior_turns=prior, current_student="give an example", current_rag="Retrieved: e.g. 'Dogs make great pets.'")
run(plan2, "turn2")
```
(Confirm `load_system_prompt`'s actual signature in `tutor/run_tutor.py` and adjust the `assignment_override` kwarg name if it differs.)

- [ ] **Step 2: Run the smoke (manual, real key)**

Run: `TUTOR_CACHED_HISTORY=1 PYTHONPATH=. python -m internal_testing.smoke_cached_history`
Expected: `turn2` prints `cache_read > 0` (the replayed prefix — static system + turn-1 student/rag/tutor — was served from cache), proving the history caches.

- [ ] **Step 3: Commit**

```bash
git add internal_testing/smoke_cached_history.py
git commit -m "test(cached-history): live smoke proving the history caches on turn 2"
```

---

## Self-Review

**Spec coverage:**
- §1 message structure → Tasks 1, 2, 6. ✅
- §2 storage (main_ui RAG column; verbatim reconstruction) → Tasks 3, 4, 1. ✅
- §3 gating — **simplified from per-conversation A/B to a single global env flag** (`TUTOR_CACHED_HISTORY`, default off), per user decision that this is throwaway validation scaffolding and cheapness is deterministic once caching works. No `history_mode` column, no assignment logic → Task 6 (`cached_history_enabled` + route gate). ✅
- §4 provider sending (Claude raw SDK; GPT langchain; legacy unchanged) → Tasks 2, 6. ✅
- §5 history shape + fail-closed → Tasks 5, 6 (fail-closed reuses existing `_enforce_rag_available`, called before the branch). ✅
- §6 cache breakpoints → Task 2 (`build_anthropic_request`). ✅
- §7 testing → Tasks 1,2,4,5,6 unit; Task 7 live smoke. ✅

**Deviation from spec (approved):** The spec (§3, Rollout) describes a per-conversation A/B via a `history_mode` column and `TUTOR_CACHED_HISTORY_RATIO`. The user simplified this to a single global `TUTOR_CACHED_HISTORY` on/off flag: the cost win is deterministic once the prefix caches (Task 7 proves it), so a traffic-split experiment is unnecessary, and the feature is throwaway scaffolding not worth a DB column + migration + assignment plumbing we would later remove. main_ui stores per-turn RAG unconditionally, so any conversation created with the flag on has replayable RAG from turn 1.

**Placeholder scan:** No TBD/TODO; every code step has real code. The one flagged unknown — the Alembic `down_revision` — is explicitly "use the actual current head" with a command to find it (Task 3, Step 1), because a concurrent migration may land first.

**Type consistency:** `build_message_plan` roles (`system_static`/`student`/`rag`/`tutor`) are consumed identically in `build_anthropic_request` (`_ROLE_MAP`) and `_plan_to_langchain`. `get_cached_history_for_tutor` emits `{student_content, rag_text, tutor_json}` — the exact keys `build_message_plan`'s `prior_turns` reads. `tutor_output_json(reasoning, answer)` signature is used consistently in Tasks 1, 5, 7.

**Known risk called out inline:** import cycle (`ui_core.services.conversation` → `ui_core.tutor_bridge` for the header) — Task 5 gives the fallback (move the header constant into `tutor/cached_history.py`).
