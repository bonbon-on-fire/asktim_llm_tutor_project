# Mandatory Per-Turn RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make per-turn RAG the shared default for both `main_ui` and `sandbox_ui`, and fail closed (raise → existing error banner, no model call) whenever RAG cannot produce grounding.

**Architecture:** Lift the RAG core (mode resolution, week scoping, retrieval, context-mode-aware assignment building) from `SandboxTutorBridge` into the shared `ui_core.TutorBridge` base so both apps run one implementation. Add a `RagUnavailableError` that the base raises before any model call when the effective mode is `rag` and retrieval returns no records; both apps' chat routes already convert a bridge exception into an `event: error` SSE frame, which the frontend renders as the "Something went wrong, please try again" banner with optimistic-bubble rollback.

**Tech Stack:** Python, LangChain/LangGraph, Flask (SSE), numpy RAG store, OpenAI embeddings. Tests are offline (no live LLM/embedding calls): `ui_core/test_tutor_bridge.py` uses a standalone `main()`/`_check` harness; sandbox route tests use pytest + monkeypatch.

## Global Constraints

- Design spec: `docs/superpowers/specs/2026-07-13-mandatory-rag-per-turn-design.md`.
- Valid context modes: `rag`, `full_context`, `exercise_only` (exact strings).
- Default mode = `rag` whenever there is a `course` and no custom context. `has_custom` degrades `rag`→`full_context`. A **missing index does NOT degrade** — it stays `rag` and fails closed at retrieval time.
- Fail-closed trigger: effective `context_mode == "rag"` AND `RetrievedContext.records` is empty (covers no-index, zero-chunks, and retrieval-threw). Raise `RagUnavailableError` **before any model call**.
- RAG grounding rides in the **system** message after the cache breakpoint (existing `retrieved_context=` plumbing) — never glued onto a student turn.
- Env escape hatch: `TUTOR_CONTEXT_MODE=full_context` forces historical behavior.
- Do NOT touch the sandbox custom-context feature or DB columns (that is Spec 2). Custom context must keep working in this plan.
- Commit message trailer: do NOT add a `Co-Authored-By: Claude` line.
- Run standalone tests with `python -m ui_core.test_tutor_bridge`; run pytest suites with `python -m pytest <path> -v`.

---

### Task 1: Lift mode-resolution + helpers + `RagUnavailableError` into `ui_core`

**Files:**
- Modify: `ui_core/tutor_bridge.py` (imports near top; add module-level constants/functions/exception after `RetrievedContext`, before `class TutorBridge`)
- Test: `ui_core/test_tutor_bridge.py` (add a `_test_mode_resolution()` block called from `main()`)

**Interfaces:**
- Produces:
  - `class RagUnavailableError(RuntimeError)` — raised when rag mode has no retrieved records.
  - `_VALID_CONTEXT_MODES: set[str] = {"rag", "full_context", "exercise_only"}`
  - `_resolve_context_mode(course: str, has_custom: bool, requested: str | None = None) -> str`
  - `_week_for_exercise(exercise) -> int | None`

- [ ] **Step 1: Add imports**

At the top of `ui_core/tutor_bridge.py`, add to the existing import block (after `from __future__ import annotations`):

```python
import os
```

and add, alongside the other third-party/first-party imports:

```python
from rag.retrieve import format_context, retrieve_scored, to_records
```

- [ ] **Step 2: Write the failing test for mode resolution**

Add this near the top of `ui_core/test_tutor_bridge.py` (after the existing imports), and call `_test_mode_resolution()` at the start of `main()` (before the stub install):

```python
def _test_mode_resolution():
    """Unit-test the lifted mode resolver and week helper (no I/O)."""
    from ui_core.tutor_bridge import _resolve_context_mode, _week_for_exercise

    prev = os.environ.pop("TUTOR_CONTEXT_MODE", None)
    try:
        _check(
            "default is rag when course present and no custom",
            _resolve_context_mode("some_course", has_custom=False) == "rag",
        )
        _check(
            "no course -> full_context",
            _resolve_context_mode("", has_custom=False) == "full_context",
        )
        _check(
            "has_custom degrades rag -> full_context",
            _resolve_context_mode("some_course", has_custom=True) == "full_context",
        )
        _check(
            "explicit exercise_only wins",
            _resolve_context_mode("some_course", has_custom=False, requested="exercise_only")
            == "exercise_only",
        )
        os.environ["TUTOR_CONTEXT_MODE"] = "full_context"
        _check(
            "env override applies when no explicit request",
            _resolve_context_mode("some_course", has_custom=False) == "full_context",
        )
        _check(
            "explicit request beats env",
            _resolve_context_mode("some_course", has_custom=False, requested="rag") == "rag",
        )
    finally:
        os.environ.pop("TUTOR_CONTEXT_MODE", None)
        if prev is not None:
            os.environ["TUTOR_CONTEXT_MODE"] = prev

    _check("numeric exercise -> week int", _week_for_exercise("4") == 4)
    _check("non-numeric exercise -> None", _week_for_exercise("custom") is None)
    _check("None exercise -> None", _week_for_exercise(None) is None)
```

Also `import os` at the top of the test file if not already present.

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m ui_core.test_tutor_bridge`
Expected: FAIL — `ImportError: cannot import name '_resolve_context_mode' from 'ui_core.tutor_bridge'`.

- [ ] **Step 4: Add the constants, exception, and helpers**

In `ui_core/tutor_bridge.py`, immediately after the `RetrievedContext` dataclass (currently ends ~line 77) and before `class TutorBridge`, add:

```python
class RagUnavailableError(RuntimeError):
    """Raised when the turn is in ``rag`` mode but retrieval produced no records.

    Covers all three no-RAG triggers uniformly (no index, zero chunks after
    week-scoping, or retrieval raised and was swallowed by ``retrieved_context``).
    The bridge raises this BEFORE any model call; the chat routes convert it to an
    ``event: error`` SSE frame, which the frontend renders as the standard error
    banner with optimistic-bubble rollback. No tutor reply is produced or persisted.
    """


# Context modes (Phase 11). ``rag`` is the default whenever a course has no custom
# context; ``full_context`` bakes course-level material into the prompt; and
# ``exercise_only`` omits it entirely. Override per-deploy with TUTOR_CONTEXT_MODE.
_VALID_CONTEXT_MODES = {"rag", "full_context", "exercise_only"}


def _resolve_context_mode(course: str, has_custom: bool, requested: str | None = None) -> str:
    """Decide how much course material to put in the prompt for this call.

    Precedence: explicit ``requested`` (valid) -> ``TUTOR_CONTEXT_MODE`` env ->
    default ``rag`` whenever there's a course and no custom context, else
    ``full_context``.

    Degrade rule: ``rag`` degrades to ``full_context`` ONLY when ``has_custom`` (a
    tester's pasted context can't be retrieved). A missing index does NOT degrade
    here — the mode stays ``rag`` and the caller fails closed at retrieval time.
    """
    requested = (requested or "").strip().lower()
    env = os.environ.get("TUTOR_CONTEXT_MODE", "").strip().lower()
    if requested in _VALID_CONTEXT_MODES:
        mode = requested
    elif env in _VALID_CONTEXT_MODES:
        mode = env
    else:
        mode = "rag" if (not has_custom and course) else "full_context"
    if mode == "rag" and has_custom:
        mode = "full_context"
    return mode


def _week_for_exercise(exercise) -> int | None:
    """The course week for the current problem, or None if not numeric.

    Exercise / practice numbers share the lecture week number, so a problem
    numbered ``4`` caps retrieval at week 4. Custom / non-numeric exercises have no
    week, so retrieval is left unscoped.
    """
    try:
        return int(str(exercise).strip())
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m ui_core.test_tutor_bridge`
Expected: PASS for the new `_test_mode_resolution` checks. (Other existing checks may still pass here — they are updated in Task 3.)

- [ ] **Step 6: Commit**

```bash
git add ui_core/tutor_bridge.py ui_core/test_tutor_bridge.py
git commit -m "feat(rag): lift context-mode resolution + RagUnavailableError into ui_core"
```

---

### Task 2: Base bridge retrieves in `rag` mode + context-mode-aware assignment/cache

**Files:**
- Modify: `ui_core/tutor_bridge.py` — `TutorBridge.prepare_ctx`, `TutorBridge.cache_key`, `TutorBridge.build_assignment_text`, `TutorBridge.retrieved_context`
- Test: `ui_core/test_tutor_bridge.py` (rewrite the base-bridge section)

**Interfaces:**
- Consumes: `_resolve_context_mode`, `_week_for_exercise`, `retrieve_scored`, `format_context`, `to_records`, `RetrievedContext` (from Task 1 + existing).
- Produces (behavior contract used by Task 3 and sandbox):
  - `prepare_ctx(course, **ctx)` returns ctx with `ctx["context_mode"]` set.
  - `retrieved_context(course, query, **ctx) -> RetrievedContext` — populated in `rag` mode, empty otherwise; never raises.
  - `build_assignment_text(course, exercise, **ctx)` drops course/syllabus/lectures unless `ctx["context_mode"] == "full_context"`.

- [ ] **Step 1: Rewrite the base-bridge test section (failing)**

In `ui_core/test_tutor_bridge.py`, replace the base `TutorBridge` block (the section under the comment `# Base TutorBridge (main_ui's behavior)` down to just before `# SandboxTutorBridge:`) with the following. It stubs the base bridge's `retrieved_context` so no real embedding call happens, and asserts the new default (rag) behavior:

```python
        # ---------------------------------------------------------------
        # Base TutorBridge (main_ui's behavior): now defaults to rag and
        # retrieves per turn. Stub retrieved_context so no real embedding runs.
        # ---------------------------------------------------------------
        bridge = tb.TutorBridge()
        bridge.retrieved_context = (
            lambda course, query, **ctx: tb.RetrievedContext(
                text="RAG_BLOCK", records=[{"source": "local:course", "score": 1.0, "chars": 3, "text": "abc"}]
            )
            if ctx.get("context_mode") == "rag"
            else tb.RetrievedContext()
        )
        history = [
            {"role": "student", "content": "Hi"},
            {"role": "tutor", "content": "Hello!"},
        ]
        result = bridge.get_tutor_reply(
            course="cities_and_climate_change",
            exercise="04",
            tutor="tutor_05",
            history=history,
            new_student_message="What now?",
        )
        _check(
            "base rag mode: reply parsed; retrieved records surfaced",
            result["reply"] == "Here is your answer."
            and result["reasoning"] == "because X"
            and result["retrieved"]
            and result["retrieved"][0]["source"] == "local:course",
            result,
        )
        messages = recorder.get_calls[-1]
        _check("history in order + new turn appended (3 total)", len(messages) == 3, len(messages))
        _check(
            "new student turn is the plain message (RAG never on a user turn)",
            _text_of(messages[2].content) == "What now?",
            messages[2].content,
        )
        _check(
            "base rag mode: retrieved block routed to the system channel",
            "RAG_BLOCK" in recorder.get_rag[-1],
            recorder.get_rag[-1],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m ui_core.test_tutor_bridge`
Expected: FAIL — the base bridge currently returns `retrieved: []` (base `retrieved_context` is empty and `prepare_ctx` never sets `context_mode`), so the stub's `ctx.get("context_mode") == "rag"` branch is never taken and `result["retrieved"]` is empty.

- [ ] **Step 3: Implement `prepare_ctx`**

Replace `TutorBridge.prepare_ctx` (currently returns `ctx` unchanged) with:

```python
    def prepare_ctx(self, course: str, **ctx) -> dict:
        """Resolve the per-call context mode and store it in ctx.

        The base bridge has no custom-context feature, so ``has_custom`` is always
        False here; subclasses that add custom context override this.
        """
        ctx["context_mode"] = _resolve_context_mode(
            course, has_custom=False, requested=ctx.get("context_mode")
        )
        return ctx
```

- [ ] **Step 4: Implement `cache_key` (include context_mode)**

Replace `TutorBridge.cache_key`:

```python
    def cache_key(self, tutor: str, course: str, exercise: str, **ctx):
        """Key for the graph/stream caches, or ``None`` to skip caching."""
        return (tutor, course, exercise, ctx.get("context_mode", "full_context"))
```

- [ ] **Step 5: Make `build_assignment_text` context-mode aware**

In `TutorBridge.build_assignment_text`, gate the course/syllabus/lecture blocks on full_context. Replace the body so the course/syllabus/lectures appends only run when `mode == "full_context"`:

```python
    def build_assignment_text(self, course: str, exercise: str, **ctx) -> str:
        """Concatenate about + (course/syllabus/lectures in full_context only) + exercise + solution key.

        In ``rag`` / ``exercise_only`` the course description, syllabus, and lecture
        transcripts are dropped — reached via retrieval (``rag``) or omitted
        (``exercise_only``). The exercise and tutor-only solution key are always kept.
        """
        mode = ctx.get("context_mode", "full_context")
        course_dir = _CURRICULUM_DIR / course
        exercise_text = exercise_path(course, exercise).read_text(encoding="utf-8").strip()

        parts: list[str] = []

        about_text = load_about_asktim()
        if about_text:
            parts.append("About yourself:\n" + about_text)

        if mode == "full_context":
            course_path = course_dir / "course.txt"
            if course_path.is_file():
                parts.append("Course context:\n" + course_path.read_text(encoding="utf-8").strip())

            syllabus_path = course_dir / "syllabus.txt"
            if syllabus_path.is_file():
                parts.append("Syllabus:\n" + syllabus_path.read_text(encoding="utf-8").strip())

            lectures = load_lecture_transcripts(course)
            if lectures:
                parts.append("Lecture transcripts:\n" + lectures)

        parts.append("Exercise:\n" + exercise_text)

        solution = read_solution(course, exercise, kind="exercise")
        if solution.strip():
            parts.append(SOLUTION_CONTEXT_LABEL + solution.strip())
        return "\n\n".join(parts)
```

- [ ] **Step 6: Implement real retrieval in `retrieved_context`**

Replace `TutorBridge.retrieved_context`:

```python
    def retrieved_context(self, course: str, query: str, **ctx) -> RetrievedContext:
        """Per-turn RAG retrieval (prompt text + records); empty outside rag mode.

        In ``rag`` mode, embeds the raw student turn, runs a week-scoped search, and
        returns the formatted block + records. Retrieval failing (e.g. no index or an
        embedding hiccup) returns empty records — the caller fails closed on that.
        """
        if ctx.get("context_mode", "full_context") != "rag":
            return RetrievedContext()
        try:
            scored = retrieve_scored(course, query, max_week=_week_for_exercise(ctx.get("exercise")))
            chunks = [c for c, _ in scored]
            return RetrievedContext(text=format_context(chunks, course), records=to_records(scored))
        except Exception:
            return RetrievedContext()
```

- [ ] **Step 7: Run test to verify it passes**

Run: `python -m ui_core.test_tutor_bridge`
Expected: PASS for the rewritten base-bridge section and Task 1 checks. (The sandbox section still passes — it stubs its own `retrieved_context`.)

- [ ] **Step 8: Commit**

```bash
git add ui_core/tutor_bridge.py ui_core/test_tutor_bridge.py
git commit -m "feat(rag): base bridge defaults to rag and retrieves per turn"
```

---

### Task 3: Fail-closed enforcement in both public methods

**Files:**
- Modify: `ui_core/tutor_bridge.py` — add `_enforce_rag_available`; call it in `get_tutor_reply` and `stream_tutor_reply`
- Test: `ui_core/test_tutor_bridge.py` (add fail-closed assertions to the base-bridge section)

**Interfaces:**
- Consumes: `RagUnavailableError`, `RetrievedContext` (Task 1), `retrieved_context` contract (Task 2).
- Produces: both public methods raise `RagUnavailableError` before any upstream model call when `context_mode == "rag"` and `rc.records` is empty.

- [ ] **Step 1: Add failing tests for the refusal**

Append to the base-bridge section of `ui_core/test_tutor_bridge.py` (after the Task 2 checks, still inside the `try:` block). It re-stubs `retrieved_context` to return empty records in rag mode and asserts the raise + that no upstream call was recorded:

```python
        # Fail closed: rag mode with empty retrieval must raise BEFORE any model call.
        bridge.retrieved_context = lambda course, query, **ctx: tb.RetrievedContext()
        before_get = len(recorder.get_calls)
        raised = False
        try:
            bridge.get_tutor_reply(
                course="cities_and_climate_change",
                exercise="04",
                tutor="tutor_05",
                history=[],
                new_student_message="What now?",
            )
        except tb.RagUnavailableError:
            raised = True
        _check("rag + empty retrieval raises RagUnavailableError (non-streaming)", raised)
        _check(
            "no upstream model call was made on refusal (non-streaming)",
            len(recorder.get_calls) == before_get,
            (before_get, len(recorder.get_calls)),
        )

        before_stream = len(recorder.stream_calls)
        raised_stream = False
        try:
            list(
                bridge.stream_tutor_reply(
                    course="cities_and_climate_change",
                    exercise="04",
                    tutor="tutor_05",
                    history=[],
                    new_student_message="What now?",
                )
            )
        except tb.RagUnavailableError:
            raised_stream = True
        _check("rag + empty retrieval raises RagUnavailableError (streaming)", raised_stream)
        _check(
            "no upstream model call was made on refusal (streaming)",
            len(recorder.stream_calls) == before_stream,
            (before_stream, len(recorder.stream_calls)),
        )

        # Non-rag mode with empty retrieval must NOT raise.
        ok_mode = True
        try:
            bridge.get_tutor_reply(
                course="cities_and_climate_change",
                exercise="04",
                tutor="tutor_05",
                history=[],
                new_student_message="What now?",
                context_mode="exercise_only",
            )
        except tb.RagUnavailableError:
            ok_mode = False
        _check("exercise_only mode with empty retrieval does NOT raise", ok_mode)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m ui_core.test_tutor_bridge`
Expected: FAIL — `RagUnavailableError` is not raised yet (base proceeds to the model call with empty context), so `raised`/`raised_stream` stay False.

- [ ] **Step 3: Add the enforcement helper**

In `ui_core/tutor_bridge.py`, add a private method to `TutorBridge` (place it just above `get_tutor_reply`):

```python
    def _enforce_rag_available(self, ctx: dict, rc: RetrievedContext) -> None:
        """Fail closed: in rag mode, refuse the turn when retrieval produced nothing.

        Covers no-index, zero-chunks, and retrieval-threw (all collapse to empty
        records). Raised before any model call so no tutor reply is produced,
        streamed, or persisted; the chat route turns it into an ``event: error`` frame.
        """
        if ctx.get("context_mode") == "rag" and not rc.records:
            raise RagUnavailableError(
                "RAG is unavailable for this turn (no retrievable course material)."
            )
```

- [ ] **Step 4: Call it in `get_tutor_reply`**

In `TutorBridge.get_tutor_reply`, immediately after the line
`rc = self.retrieved_context(course, new_student_message, exercise=exercise, **ctx)`
add:

```python
        self._enforce_rag_available(ctx, rc)
```

(It must sit before `_upstream_get_tutor_reply(...)`.)

- [ ] **Step 5: Call it in `stream_tutor_reply`**

In `TutorBridge.stream_tutor_reply`, immediately after the line
`rc = self.retrieved_context(course, new_student_message, exercise=exercise, **ctx)`
add:

```python
        self._enforce_rag_available(ctx, rc)
```

(It must sit before the `for item in _upstream_stream_tutor_reply(...)` loop. Because this is a generator, the raise surfaces on first iteration — before any model streaming — and the route's `try/except` converts it to `event: error`.)

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m ui_core.test_tutor_bridge`
Expected: PASS — all checks including the new refusal and no-upstream-call assertions.

- [ ] **Step 7: Commit**

```bash
git add ui_core/tutor_bridge.py ui_core/test_tutor_bridge.py
git commit -m "feat(rag): fail closed when rag mode has no retrieved records"
```

---

### Task 4: Slim `SandboxTutorBridge` to inherit the lifted core

**Files:**
- Modify: `sandbox_ui/services/tutor_bridge.py` (remove duplicated helpers + the `retrieved_context` override; import lifted helpers; drop now-unused imports)
- Test: `python -m ui_core.test_tutor_bridge` and `python -m sandbox_ui.services.test_tutor_bridge_practice`

**Interfaces:**
- Consumes: `_resolve_context_mode` (from `ui_core.tutor_bridge`), inherited base `retrieved_context` / `_enforce_rag_available`.
- Produces: `SandboxTutorBridge` behavior unchanged for `full_context`/`exercise_only`/custom modes; rag mode now inherits the fail-closed base.

- [ ] **Step 1: Update imports in `sandbox_ui/services/tutor_bridge.py`**

Change the import block so the shared helper comes from `ui_core` and the now-unused `rag`/`has_index` imports are dropped. Replace:

```python
from rag.retrieve import format_context
from rag.retrieve import has_index as rag_has_index
from rag.retrieve import retrieve_scored, to_records
from tutor.run_tutor import load_system_prompt
from ui_core.tutor_bridge import RetrievedContext, TutorBridge
```

with:

```python
from tutor.run_tutor import load_system_prompt
from ui_core.tutor_bridge import (
    TutorBridge,
    _resolve_context_mode,
    _week_for_exercise,
)
```

(`RetrievedContext` is no longer referenced in this file after Step 3; `format_context`/`retrieve_scored`/`to_records`/`rag_has_index` were only used by the removed helpers.)

- [ ] **Step 2: Delete the module-level `_VALID_CONTEXT_MODES` and `_resolve_context_mode`**

Remove these from `sandbox_ui/services/tutor_bridge.py` (now provided by `ui_core.tutor_bridge`):
- the `_VALID_CONTEXT_MODES = {...}` assignment,
- the entire `def _resolve_context_mode(...)` function.

- [ ] **Step 3: Delete the module-level `_week_for_exercise` and `_retrieved_context`**

Remove from `sandbox_ui/services/tutor_bridge.py`:
- the entire `def _week_for_exercise(...)` function (now imported from `ui_core`),
- the entire `def _retrieved_context(...)` function (the base `TutorBridge.retrieved_context` replaces it).

- [ ] **Step 4: Remove the `retrieved_context` override on `SandboxTutorBridge`**

Delete this method from the `SandboxTutorBridge` class body (the inherited base implementation is identical in effect — it reads `ctx["context_mode"]` and `_week_for_exercise(ctx.get("exercise"))`):

```python
    def retrieved_context(self, course: str, query: str, **ctx) -> RetrievedContext:
        return _retrieved_context(
            course,
            ctx.get("context_mode", "full_context"),
            query,
            _week_for_exercise(ctx.get("exercise")),
        )
```

Leave `prepare_ctx`, `cache_key`, `build_assignment_text`, `build_system_prompt`, and `turn_attachments` intact. `prepare_ctx` still calls `_resolve_context_mode(course, has_custom, requested=ctx.get("context_mode"))` — now resolved via the `ui_core` import.

- [ ] **Step 5: Run the affected test suites**

Run: `python -m ui_core.test_tutor_bridge`
Expected: PASS (this file imports `SandboxTutorBridge`; it must still import and run).

Run: `python -m sandbox_ui.services.test_tutor_bridge_practice`
Expected: PASS (build_assignment_text practice/exercise resolution unaffected).

- [ ] **Step 6: Commit**

```bash
git add sandbox_ui/services/tutor_bridge.py
git commit -m "refactor(rag): sandbox bridge inherits lifted rag core from ui_core"
```

---

### Task 5: Route-level test — refusal emits an `event: error` frame

**Files:**
- Create: `sandbox_ui/routes/test_chat_rag_fail_closed.py`
- Test: `python -m pytest sandbox_ui/routes/test_chat_rag_fail_closed.py -v`

**Interfaces:**
- Consumes: the real `sandbox_ui.services.tutor_bridge.stream_tutor_reply` → base `_enforce_rag_available` → `RagUnavailableError`; the chat route's existing `try/except` → `event: error`.
- Produces: proof that a rag turn whose retrieval is empty yields an `error` SSE frame and no `done` frame.

- [ ] **Step 1: Write the failing test**

Model it on `sandbox_ui/routes/test_chat_files_e2e.py` (same fixtures/client). Instead of monkeypatching `stream_tutor_reply`, monkeypatch the retrieval so the REAL bridge fails closed. Create `sandbox_ui/routes/test_chat_rag_fail_closed.py`:

```python
"""Route-level test: a rag-mode turn with no retrievable material fails closed.

The real bridge stream runs; only retrieval is stubbed empty, so the base
``_enforce_rag_available`` raises ``RagUnavailableError`` and the chat route
converts it into an ``event: error`` SSE frame (no ``done`` frame).
"""

from __future__ import annotations

import ui_core.tutor_bridge as tb


def _empty_retrieval(self, course, query, **ctx):
    """Force rag mode to see no retrieved records (empty index simulation)."""
    return tb.RetrievedContext()


def test_rag_turn_without_material_emits_error_frame(client, monkeypatch):
    """A rag-mode chat turn with empty retrieval yields an SSE error frame, no done."""
    # Force rag mode and empty retrieval on the shared bridge base.
    monkeypatch.setenv("TUTOR_CONTEXT_MODE", "rag")
    monkeypatch.setattr(tb.TutorBridge, "retrieved_context", _empty_retrieval)

    resp = client.post(
        "/api/chat",
        json={
            "text": "Explain urban heat islands",
            "course": "cities_and_climate_change",
            "exercise": "4",
        },
    )
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "event: error" in body
    assert "event: done" not in body
```

If `client` (and any auth/session) fixtures are not already provided by a shared `conftest.py`, reuse the exact fixture setup from `sandbox_ui/routes/test_chat_files_e2e.py` (copy its fixture imports / `client` construction) so this test stands up the app the same way.

- [ ] **Step 2: Run test to verify it fails (or errors) first**

Run: `python -m pytest sandbox_ui/routes/test_chat_rag_fail_closed.py -v`
Expected: Before Tasks 2-3 are in place this would not refuse; after them it should pass. If it fails, inspect whether the sandbox default resolved to `rag` (env forces it) and whether the monkeypatched `retrieved_context` is on the class the bridge instantiates.

- [ ] **Step 3: Make it pass**

No new product code should be required — Tasks 2-4 provide the behavior. If the test cannot construct a `client`, add the minimal fixture wiring copied from `test_chat_files_e2e.py`. Adjust only the test until it passes.

- [ ] **Step 4: Run to verify it passes**

Run: `python -m pytest sandbox_ui/routes/test_chat_rag_fail_closed.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sandbox_ui/routes/test_chat_rag_fail_closed.py
git commit -m "test(rag): route emits error frame when rag turn has no material"
```

---

### Task 6: Documentation

**Files:**
- Modify: `tutor/README.md`, `rag/README.md`, `main_ui/README.md`, `sandbox_ui/README.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Update `rag/README.md`**

Under the "Retrieve (used by the tutor)" section, add a short note:

```markdown
### Mandatory RAG (fail-closed)

RAG is the **default** context mode in both apps (`ui_core.TutorBridge`): a turn
uses `rag` whenever the course has no custom context. When the effective mode is
`rag` and retrieval returns **no records** — no index, zero chunks after
`max_week` scoping, or an embedding/search error — the bridge raises
`RagUnavailableError` **before any model call**. The chat route converts that into
an `event: error` SSE frame, so the student sees the standard "Something went
wrong" banner and no tutor turn is produced or persisted. A missing index does
NOT silently fall back to full context. Set `TUTOR_CONTEXT_MODE=full_context` to
force the historical baked-in behavior deploy-wide.
```

- [ ] **Step 2: Update `tutor/README.md`**

In "What the tutor receives each turn", add a sentence noting RAG is now the shared default and fail-closed (raise → error banner) rather than degrading to full context.

- [ ] **Step 3: Update `main_ui/README.md` and `sandbox_ui/README.md`**

Add a one-line note to each that main_ui now runs per-turn RAG by default (all shipped courses have an index) and that both apps fail closed when RAG is unavailable, with `TUTOR_CONTEXT_MODE=full_context` as the escape hatch.

- [ ] **Step 4: Commit**

```bash
git add tutor/README.md rag/README.md main_ui/README.md sandbox_ui/README.md
git commit -m "docs(rag): document mandatory fail-closed per-turn RAG"
```

---

## Self-Review

**Spec coverage:**
- §1 lift core → Tasks 1, 2, 4. §2 mode resolution → Task 1 (+ default applied in Task 2 `prepare_ctx`). §3 fail closed → Task 3. §4 error surfacing (reuse routes) → verified by Task 5. §5 scope of effect (main_ui inherits; sandbox rag-only refusal) → Tasks 2-4 + Task 5. §6 UX note → no code. Testing section → Tasks 2, 3, 5. Files-touched list matches Tasks 1-6. Escape hatch (`TUTOR_CONTEXT_MODE`) → Task 1 resolver + Task 6 docs.
- No spec requirement is left without a task.

**Placeholder scan:** No TBD/TODO; every code step shows complete code; test steps include real assertions. The only conditional ("if `client` fixtures aren't shared, copy them from `test_chat_files_e2e.py`") names the exact source file to copy from.

**Type/name consistency:** `RagUnavailableError`, `_resolve_context_mode`, `_week_for_exercise`, `_VALID_CONTEXT_MODES`, `RetrievedContext(text, records)`, `_enforce_rag_available(ctx, rc)`, `retrieved_context(course, query, **ctx)`, and `context_mode` are used identically across Tasks 1-5. `retrieve_scored(course, query, max_week=...)` matches `rag/retrieve.py`. Sandbox `prepare_ctx` keeps calling `_resolve_context_mode(course, has_custom, requested=...)` — now imported from `ui_core`.
