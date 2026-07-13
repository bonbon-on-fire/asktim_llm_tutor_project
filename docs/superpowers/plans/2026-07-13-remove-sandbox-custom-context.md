# Remove Sandbox Custom Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the sandbox "paste-your-own text" capability (the five `custom_*` overrides + custom tutor prompt) while keeping the Create-context wizard's built-in course/exercise/practice selection, the include-toggles, and the RAG-mode selector.

**Architecture:** Peel custom-text support outside-in so the app stays consistent after each task: frontend stops sending it → routes stop reading/threading it and drop the preview endpoint → bridge drops custom params and slims `SandboxTutorBridge` → service/DB drop the columns via a boot-time `DROP COLUMN` step → docs. Sandbox has no Alembic; schema is `create_all` + a hand-rolled boot reconciler, so the column drop is a guarded boot step, not a migration.

**Tech Stack:** Python, Flask (SSE), SQLAlchemy, vanilla JS wizard. Tests: `ui_core/test_tutor_bridge.py` and `sandbox_ui/*/test_*.py` standalone `main()`/`_check` harnesses run via `python -m ...`; route tests via `python -m pytest`. All offline.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-13-remove-sandbox-custom-context-design.md`.
- REMOVE only: the 5 `custom_*` request fields / DB columns (`custom_course_text`, `custom_exercise_text`, `custom_tutor_prompt`, `custom_syllabus_text`, `custom_lectures_text`), the custom-tutor-prompt path, and the custom-text wizard UI + `/api/context/preview`.
- KEEP: the wizard's built-in course/exercise/practice selection, the include-toggles (`course_enabled`/`syllabus_enabled`/`lectures_enabled`), the RAG-mode selector (`context_mode`), `exercise_kind`/practice support, and the tutor lock (`tutor_06`).
- Do NOT change `ui_core/*` or `main_ui/*` — `ui_core.services.conversation` is generic (no sandbox column names) and must stay that way.
- The 5 `custom_*` columns are all nullable — removing them from the ORM does not break INSERTs; the boot-step drop is for cleanliness of the long-lived Postgres.
- Git commit messages must NOT contain a `Co-Authored-By: Claude` trailer.
- Only `git add` the files named in each task.
- Run standalone tests with `python -m <module>`; pytest suites with `python -m pytest <path> -q`.

---

### Task 1: Frontend — remove custom-text from the wizard

**Files:**
- Modify: `sandbox_ui/static/js/chat.js`
- Modify: `sandbox_ui/static/css/sandbox-extra.css`
- Modify: `sandbox_ui/templates/embed.html` (only if a block empties out)

**Interfaces:**
- Produces: the wizard now emits only built-in selections; the `/api/chat` send payload no longer includes `course_custom`/`exercise_custom`/`tutor_custom`/`syllabus_custom`/`lectures_custom`. `exercise_kind`, `course_enabled`, `syllabus`, `lectures`, `context_mode` are still sent.

This is intricate existing JS (~590 wizard lines). Remove the custom-text paths precisely and preserve everything built-in. Read the wizard region (`chat.js:820-1339`) before editing.

- [ ] **Step 1: Remove the `CUSTOM` option + custom textarea + preview from step rendering**

In `chat.js` `renderCreateStep()` (~896-1194):
- Delete the trailing `{ value: CUSTOM, label: "Create custom …" }` entry from the `options` array in the `course` (line ~915), `exercise` (~937), `lectures` (~971), and `syllabus` (~987) steps.
- Delete the `create-custom` textarea creation block (lines ~1008-1012: `const ta = document.createElement("textarea"); ta.className = "create-custom"; … createStepBody.appendChild(ta);`) and any code that shows/hides it or writes `customValue`/preview text into it. Remove the `customValue`/`placeholder` locals if they become unused.
- Keep the built-in `<select>` (`buildSelect`), the course-description toggle (`create-course-desc-toggle`, ~1017-1035), and the RAG toggle (~1014-1038).

- [ ] **Step 2: Remove the tutor step and the `CUSTOM` sentinel + preview fetch**

- In the step list (`CREATE_STEPS`/`activeSteps()`, ~822-838), remove `"tutor"` so the wizard has no tutor step (tutor is locked to `tutor_06`). Remove the `else if (step === "tutor")` branch (~954-962) in `renderCreateStep()`.
- Delete `fetchPreviewText` (~842-869) and every call to it (it only ever populated the custom textarea).
- Delete the `CUSTOM` sentinel constant (~839) once no longer referenced.

- [ ] **Step 3: Remove custom mapping from `finishCreate()` and the send payload + config defaults**

- In `finishCreate()` (~1260-1339), stop reading/emitting `courseCustom`/`exerciseCustom`/`tutorCustom`/`syllabusCustom`/`lecturesCustom` and any `mode === "custom"` branches; every selection is now a built-in `existing` value (+ kind for exercise/practice). Keep `courseEnabled`, `syllabus`, `lectures`, `exerciseKind`, `contextMode`, and `tutor` (always `tutor_06`).
- In the send handler (~1523-1539), remove the lines that send `course_custom`/`exercise_custom`/`tutor_custom`/`syllabus_custom`/`lectures_custom`. Keep `exercise_kind`, `course_enabled`, `syllabus`, `lectures`, `context_mode`.
- In the config defaults (~6-25), remove `courseCustom`/`exerciseCustom`/`tutorCustom`/`syllabusCustom`/`lecturesCustom` (and `contextMode`/`exerciseKind` only if truly unused — they are still used, so keep them).

- [ ] **Step 4: Remove dead CSS**

In `sandbox_ui/static/css/sandbox-extra.css`, delete the now-unused `.create-custom` (and its `:focus`, `:read-only`) rules, plus the already-dead `.context-field`/`.context-label`/`.context-checkbox` (+children)/`.lock-icon`/`.context-checkbox input:disabled + span` rules. KEEP `.create-step-body`, `.create-actions`(+`-right`), `.context-select`(+`:focus`/`:disabled`), `.rag-toggle`, and everything outside the wizard.

- [ ] **Step 5: Check the template**

Read `sandbox_ui/templates/embed.html`. The create-context button (~7-20) and modal (~48-65) STAY (the wizard still runs). Only edit if a sub-element became orphaned; otherwise leave it. Do NOT remove the `#testing-modal` block.

- [ ] **Step 6: Verify JS parses and nothing built-in regressed**

Run: `node --check sandbox_ui/static/js/chat.js`
Expected: exits 0 (no output).
Then grep the file to confirm no dangling references remain:
Run: `grep -nE "CUSTOM|create-custom|fetchPreviewText|Custom|context/preview" sandbox_ui/static/js/chat.js`
Expected: no matches for `CUSTOM` sentinel usage, `create-custom`, `fetchPreviewText`, `*Custom` payload keys, or `context/preview` (the wizard no longer references any custom-text path). Report any remaining line for reconciliation.

- [ ] **Step 7: Bump the chat.js cache-bust version**

In `sandbox_ui/templates/embed.html`, the chat.js `<script>` uses `v='13'` (`{% block chat_js_src %}...v='13'...`). Increment it to `v='14'` so browsers fetch the new file.

- [ ] **Step 8: Commit**

```bash
git add sandbox_ui/static/js/chat.js sandbox_ui/static/css/sandbox-extra.css sandbox_ui/templates/embed.html
git commit -m "feat(sandbox): drop custom-text steps from the context wizard"
```

---

### Task 2: Routes — stop reading/threading custom; remove `/api/context/preview`

**Files:**
- Modify: `sandbox_ui/routes/chat.py`
- Modify: `sandbox_ui/routes/embed.py`
- Modify: `sandbox_ui/routes/_validation.py`
- Modify: `sandbox_ui/routes/test_validation_practice.py`
- Create: `sandbox_ui/routes/test_chat_custom_ignored.py`

**Interfaces:**
- Consumes: the bridge module wrappers still accept the custom kwargs (defaulted) at this point — Task 2 simply stops passing them; Task 3 removes them.
- Produces: `/api/chat` ignores any `*_custom` request field; `/api/context/preview` no longer exists; `load_*_text` preview helpers are gone.

- [ ] **Step 1: Write the failing "custom ignored" route test**

Create `sandbox_ui/routes/test_chat_custom_ignored.py`. Model the client/fixture usage on `sandbox_ui/routes/test_chat_files_e2e.py` (reuse the `client` fixture from `sandbox_ui/routes/conftest.py`). Stub the tutor stream so no live call happens, and capture the kwargs the bridge receives:

```python
"""Route test: a /api/chat turn's custom_* fields are ignored (feature removed).

The conversation is created against the built-in course/exercise, and no custom
text reaches the tutor bridge. The tutor stream is stubbed so no live LLM call runs.
"""

from __future__ import annotations

import sandbox_ui.services.tutor_bridge as tutor_bridge


def _fake_stream(**kwargs):
    """Capture kwargs, yield one delta + done. Records into _CAPTURED."""
    _CAPTURED.clear()
    _CAPTURED.update(kwargs)
    yield {"type": "delta", "text": "hi"}
    yield {"type": "done", "reply": "hi", "reasoning": None, "retrieved": None}


_CAPTURED: dict = {}


def test_custom_fields_are_ignored(client, monkeypatch):
    """A course_custom in the request does not change the stored course or reach the bridge."""
    monkeypatch.setattr(tutor_bridge, "stream_tutor_reply", _fake_stream)
    resp = client.post(
        "/api/chat",
        json={
            "text": "hello",
            "course": "cities_and_climate_change",
            "exercise": "4",
            "course_custom": "MALICIOUS OVERRIDE TEXT",
            "exercise_custom": "X",
            "tutor_custom": "Y",
        },
    )
    assert resp.status_code == 200
    # The bridge must have been called for the built-in course, with no custom kwargs.
    assert _CAPTURED.get("course") == "cities_and_climate_change"
    assert "course_text" not in _CAPTURED
    assert "exercise_text" not in _CAPTURED
    assert "custom_tutor_prompt" not in _CAPTURED
    assert "MALICIOUS OVERRIDE TEXT" not in str(_CAPTURED)
```

If the `client` fixture needs anything beyond `conftest.py`, copy the exact setup from `test_chat_files_e2e.py`.

- [ ] **Step 2: Run the test to see it fail**

Run: `python -m pytest sandbox_ui/routes/test_chat_custom_ignored.py -q`
Expected: FAIL — currently `chat.py` reads `course_custom` and passes `course_text=...`/`custom_tutor_prompt=...` into `stream_kwargs`, so `_CAPTURED` contains `course_text`/`custom_tutor_prompt` and the malicious text.

- [ ] **Step 3: Remove custom handling from `chat.py`**

In `sandbox_ui/routes/chat.py`:
- Delete the reads of `course_custom`/`exercise_custom`/`tutor_custom`/`syllabus_custom`/`lectures_custom` (~182-188).
- Delete the custom-context validation branch that sets `course`/`exercise`/`tutor` to the literal `"custom"` and skips file validation (within ~207-236) — keep the normal `validate_course`/`validate_selection`/`validate_tutor` path so every turn validates a real built-in.
- Remove the 5 custom kwargs from the `find_or_create_conversation(...)` call (~256-274).
- Delete the `convo.custom_*` snapshot reads (~330-347) and remove `course_text`/`exercise_text`/`syllabus_text`/`lectures_text`/`custom_tutor_prompt` from `stream_kwargs` (~361-378). Keep `exercise_kind`, `include_course`/`include_syllabus`/`include_lectures`, `context_mode`.

- [ ] **Step 4: Remove `/api/context/preview` from `embed.py` and the preview helpers from `_validation.py`**

- In `sandbox_ui/routes/embed.py`, delete the `/api/context/preview` route (~69-109). Keep `/api/context/options`, `GET /embed`, `GET /`.
- In `sandbox_ui/routes/_validation.py`, delete `load_course_text`, `load_exercise_text`, `load_practice_text`, `load_tutor_text`, `load_syllabus_text`, `load_lectures_text` (they had no other consumer). Keep `list_context_options`, `list_tutors`, `course_has_syllabus`/`course_has_lectures`/`course_has_rag`, `validate_*`, `load_course_name`, and the `DEFAULT_*` constants. Confirm nothing else imports the removed helpers (grep `load_.*_text` under `sandbox_ui/`).

- [ ] **Step 5: Fix `test_validation_practice.py`**

In `sandbox_ui/routes/test_validation_practice.py`, delete the single line that asserts `load_practice_text` (line ~40: `_check("load_practice_text", V.load_practice_text(...) ...)`). Keep the `list_practice`/`validate_practice`/`list_context_options` assertions.

- [ ] **Step 6: Run tests to green**

Run: `python -m pytest sandbox_ui/routes/test_chat_custom_ignored.py -q`
Expected: PASS.
Run: `python -m sandbox_ui.routes.test_validation_practice`
Expected: PASS (with the `load_practice_text` assertion removed).
Run: `python -m pytest sandbox_ui/ -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add sandbox_ui/routes/chat.py sandbox_ui/routes/embed.py sandbox_ui/routes/_validation.py sandbox_ui/routes/test_validation_practice.py sandbox_ui/routes/test_chat_custom_ignored.py
git commit -m "feat(sandbox): stop honoring custom-context fields; drop preview endpoint"
```

---

### Task 3: Bridge — remove custom support, slim `SandboxTutorBridge`

**Files:**
- Modify: `sandbox_ui/services/tutor_bridge.py`
- Test: `python -m ui_core.test_tutor_bridge`, `python -m sandbox_ui.services.test_tutor_bridge_practice`

**Interfaces:**
- Consumes: routes no longer pass custom kwargs (Task 2), so removing them from the wrappers is safe.
- Produces: `build_assignment_text(course, exercise, *, exercise_kind, include_course, include_syllabus, include_lectures, context_mode)` (no `*_text` params); no `_render_custom_tutor_prompt`/`_has_custom`; `SandboxTutorBridge` keeps only `cache_key` + `build_assignment_text` overrides.

- [ ] **Step 1: Remove custom params from module-level `build_assignment_text`**

In `sandbox_ui/services/tutor_bridge.py`, edit `build_assignment_text` (~42-149): drop the `course_text`/`exercise_text`/`syllabus_text`/`lectures_text` parameters and their "custom text wins" branches. Course/syllabus/lectures now come only from the on-disk built-in files, gated by `include_course`/`include_syllabus`/`include_lectures` AND `context_mode == "full_context"` (unchanged gating). Keep `exercise_kind` (exercise vs practice path) and the tutor-only solution key.

- [ ] **Step 2: Delete `_render_custom_tutor_prompt` and `_has_custom`**

Delete both functions (~152-176 and ~179-190). Grep the file to confirm no remaining references.

- [ ] **Step 3: Slim `SandboxTutorBridge`**

- Remove the `prepare_ctx` override — the base `TutorBridge.prepare_ctx` already resolves `context_mode` with `has_custom=False`, which is now correct.
- Remove the `build_system_prompt` override — with no `custom_tutor_prompt`, it reduces to the base's `load_system_prompt(tutor, ...)`.
- Remove the `turn_attachments` override — with no custom course/exercise, the base figure-discovery behavior is correct.
- In `cache_key`, delete the `has_custom → None` early return; keep the tuple that also keys on `include_course`/`include_syllabus`/`include_lectures`/`exercise_kind`/`context_mode`.
- Keep the `build_assignment_text` override (it threads the toggles/kind/mode kwargs into the module-level function).

- [ ] **Step 4: Remove custom kwargs from the module-level wrappers**

In `get_tutor_reply` and `stream_tutor_reply` (~271-373), drop the `course_text`/`exercise_text`/`syllabus_text`/`lectures_text`/`custom_tutor_prompt` parameters and stop forwarding them. Keep `exercise_kind`, `include_course`/`include_syllabus`/`include_lectures`, `context_mode`.

- [ ] **Step 5: Confirm no test references a removed symbol**

Grep `ui_core/test_tutor_bridge.py` and `sandbox_ui/services/test_tutor_bridge_practice.py` for `_has_custom`, `_render_custom_tutor_prompt`, `course_text`, `custom_tutor_prompt`, `prepare_ctx`, `build_system_prompt`, `turn_attachments`. If the `ui_core` test constructs `SandboxTutorBridge` and stubs `retrieved_context` (it does), confirm that still works after the slim (retrieved_context is inherited from base). Update any assertion that referenced a removed override.

- [ ] **Step 6: Run tests**

Run: `python -m ui_core.test_tutor_bridge`
Expected: PASS (the sandbox section stubs `retrieved_context`; slimmed subclass still resolves `context_mode` via inherited `prepare_ctx`).
Run: `python -m sandbox_ui.services.test_tutor_bridge_practice`
Expected: PASS (`build_assignment_text(course, "1", exercise_kind=...)` still resolves exercise vs practice).
Run: `python -m pytest sandbox_ui/ -q`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add sandbox_ui/services/tutor_bridge.py
git commit -m "refactor(sandbox): drop custom-context bridge code, slim SandboxTutorBridge"
```

---

### Task 4: Service + DB — drop the columns via a boot step

**Files:**
- Modify: `sandbox_ui/services/conversation.py`
- Modify: `sandbox_ui/db/models.py`
- Modify: `sandbox_ui/run_app.py`
- Test: `sandbox_ui/db/test_drop_custom_columns.py` (create)

**Interfaces:**
- Consumes: nothing reads `convo.custom_*` after Task 2/3.
- Produces: `Conversation` has no `custom_*` columns; a guarded boot step drops them from an existing DB.

- [ ] **Step 1: Remove custom kwargs from the conversation service**

In `sandbox_ui/services/conversation.py`, remove the five `custom_*` parameters from `find_or_create_conversation` (~30-77) and delete their keys from the `extra_fields` dict (~65-76). Leave `exercise_kind`/`*_enabled`/`context_mode` in place. `_summarize_extra` (~149-156) did not include custom fields — leave it. Do NOT touch `ui_core.services.conversation`.

- [ ] **Step 2: Remove the 5 columns from the model**

In `sandbox_ui/db/models.py`, delete the `custom_course_text`, `custom_exercise_text`, `custom_tutor_prompt`, `custom_syllabus_text`, `custom_lectures_text` column definitions (~72-76) from `Conversation`. Keep `exercise_kind`, `course_enabled`, `syllabus_enabled`, `lectures_enabled`, `context_mode`, and `Message.retrieved_context`.

- [ ] **Step 3: Write the failing boot-step test**

Create `sandbox_ui/db/test_drop_custom_columns.py`. Build a temp SQLite DB with a `conversations` table that HAS the 5 custom columns, run the new drop function, assert they're gone and that a second run is a no-op; also assert a fresh table WITHOUT them is a no-op:

```python
"""Test the one-time boot step that drops the removed custom_* columns.

Uses a temp SQLite file; asserts idempotence and fresh-DB no-op.
"""

from __future__ import annotations

import sqlalchemy as sa

from sandbox_ui.run_app import _drop_custom_context_columns

_CUSTOM = [
    "custom_course_text",
    "custom_exercise_text",
    "custom_tutor_prompt",
    "custom_syllabus_text",
    "custom_lectures_text",
]


def _columns(engine, table):
    return {c["name"] for c in sa.inspect(engine).get_columns(table)}


def test_drops_custom_columns_idempotently(tmp_path):
    """Existing custom_* columns are dropped; re-running is a no-op; fresh DB unaffected."""
    engine = sa.create_engine(f"sqlite:///{tmp_path/'t.db'}")
    with engine.begin() as conn:
        cols = ", ".join(f"{c} TEXT" for c in _CUSTOM)
        conn.execute(sa.text(f"CREATE TABLE conversations (id INTEGER PRIMARY KEY, course TEXT, {cols})"))
    assert set(_CUSTOM).issubset(_columns(engine, "conversations"))

    _drop_custom_context_columns(engine)
    remaining = _columns(engine, "conversations")
    assert not (set(_CUSTOM) & remaining)
    assert "course" in remaining  # untouched

    # Idempotent: second run does not error and changes nothing.
    _drop_custom_context_columns(engine)
    assert not (set(_CUSTOM) & _columns(engine, "conversations"))
```

- [ ] **Step 4: Run the test to see it fail**

Run: `python -m pytest sandbox_ui/db/test_drop_custom_columns.py -q`
Expected: FAIL — `ImportError: cannot import name '_drop_custom_context_columns'`.

- [ ] **Step 5: Implement the boot step**

In `sandbox_ui/run_app.py`, add `_drop_custom_context_columns(engine)`, modeled on the existing `_reconcile_columns`/`_migrate_email_to_username` pattern (use `sqlalchemy.inspect(engine)` to read the live columns). For each of the five `custom_*` names that IS present on the `conversations` table, run `ALTER TABLE conversations DROP COLUMN <name>`. Guard on existence (do not use `IF EXISTS` — SQLite lacks it). Wrap the whole thing so a fresh DB (no such columns) is a clean no-op. Then wire it into `on_startup` after `create_all` + `_reconcile_columns` (alongside `_migrate_email_to_username`).

```python
def _drop_custom_context_columns(engine) -> None:
    """One-time: drop the removed custom_* Conversation columns if present.

    Sandbox has no Alembic; this mirrors the hand-rolled boot reconciler. Idempotent
    and safe on a fresh DB (create_all never creates these now) and on both SQLite
    (local dev) and Postgres (prod). The dropped snapshots are disposable test data.
    """
    import sqlalchemy as sa

    removed = (
        "custom_course_text",
        "custom_exercise_text",
        "custom_tutor_prompt",
        "custom_syllabus_text",
        "custom_lectures_text",
    )
    inspector = sa.inspect(engine)
    if "conversations" not in inspector.get_table_names():
        return
    existing = {c["name"] for c in inspector.get_columns("conversations")}
    to_drop = [name for name in removed if name in existing]
    if not to_drop:
        return
    with engine.begin() as conn:
        for name in to_drop:
            conn.execute(sa.text(f'ALTER TABLE conversations DROP COLUMN {name}'))
```

Wire-up (in the existing `on_startup` lambda/function that runs `create_all`, `_reconcile_columns`, `_migrate_email_to_username`): add a call to `_drop_custom_context_columns(engine)` after `_reconcile_columns(...)`.

- [ ] **Step 6: Run the boot-step test + full suite**

Run: `python -m pytest sandbox_ui/db/test_drop_custom_columns.py -q`
Expected: PASS.
Run: `python -m pytest -q`
Expected: all pass.
Run: `python -m ui_core.test_tutor_bridge` and `python -m sandbox_ui.services.test_tutor_bridge_practice` and `python -m sandbox_ui.routes.test_validation_practice`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add sandbox_ui/services/conversation.py sandbox_ui/db/models.py sandbox_ui/run_app.py sandbox_ui/db/test_drop_custom_columns.py
git commit -m "feat(sandbox): drop custom_* columns from Conversation + boot-step cleanup"
```

---

### Task 5: Docs — rewrite the sandbox README custom-context sections

**Files:**
- Modify: `sandbox_ui/README.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Update the README**

Read `sandbox_ui/README.md` and remove the custom-context material while keeping the wizard/toggle/mode/practice docs:
- Top summary (~1-28): drop mentions of custom course/exercise/syllabus/lectures/tutor text; the wizard is now built-in selection + toggles + RAG mode only.
- Architecture (~30-67): update the `SandboxTutorBridge` description (now only `cache_key` + `build_assignment_text` overrides; `prepare_ctx`/`build_system_prompt`/`turn_attachments` inherited); update the `Conversation` column list to 5 sandbox-only columns (`exercise_kind`, 3× `*_enabled`, `context_mode`) — the 5 `custom_*` are gone; drop the `/api/context/preview` reference.
- "The 'Create context' wizard" section (~82-128): remove the custom-text bullets/steps; keep built-in selection, toggles, RAG mode, practice.
- Database section (~164-226): update the column list; note the boot-step drop replaces the old `custom_*` reconcile-add.
- API surface (~228-274): remove the `/api/context/preview` row and the `*_custom` request-field bullet; keep `/api/context/options`, `context_mode`, `exercise_kind`, `*_enabled`.
- Layout tree comments (~290-322): drop custom/preview call-outs.

- [ ] **Step 2: Commit**

```bash
git add sandbox_ui/README.md
git commit -m "docs(sandbox): remove custom-context from the README"
```

---

## Self-Review

**Spec coverage:** §1 frontend → Task 1. §2 routes → Task 2. §3 validation (`load_*_text` + `/api/context/preview`) → Task 2. §4 bridge → Task 3. §5 DB drop (boot step) → Task 4. §6 service + tests + docs → Tasks 2 (custom-ignored test), 4 (service), 5 (docs). §7 remaining `SandboxTutorBridge` shape → Task 3. Testing section → Tasks 2/3/4. Every spec section maps to a task.

**Placeholder scan:** No TBD/TODO. Test steps contain real assertions; the boot-step and both new tests have complete code. The frontend task uses named anchors (`CUSTOM`, `create-custom`, `fetchPreviewText`, the four steps, `finishCreate`, payload keys) rather than full line-by-line JS because the wizard is ~590 intertwined lines — each removal target is named precisely and Step 6 greps to confirm none remain.

**Type/name consistency:** `_drop_custom_context_columns(engine)` is defined in Task 4 Step 5 and imported by the Task 4 Step 3 test under the same name. The five `custom_*` names are used identically across Tasks 2/3/4. `build_assignment_text` keeps `exercise_kind`/`include_*`/`context_mode` across Tasks 1-3. `stream_tutor_reply`/`get_tutor_reply` wrapper kwargs match what `chat.py` passes after Task 2's trimming.

**Ordering/consistency:** Each task leaves the app runnable — frontend stops sending custom (Task 1) before routes stop reading it (Task 2) before the bridge drops the params (Task 3) before the service/DB drop the columns (Task 4). No task references a symbol a later task is meant to define.
