# Spec 2 — Remove custom free-text context from sandbox

Date: 2026-07-13
Status: Design approved; implementation plan pending.
Follows: `2026-07-13-mandatory-rag-per-turn-design.md` (Spec 1) and the
`feat(sandbox): lock the tutor prompt to tutor_06` change.

## Goal

Remove the sandbox "paste-your-own text" capability — the five custom context
overrides and the custom tutor prompt — while **keeping the Create-context
wizard** for built-in selection (course / exercise / practice), the include
toggles (course / syllabus / lectures), and the RAG-mode selector. After this
change a sandbox tester can pick among built-in curriculum + tutor_06 + context
mode, but can no longer inject arbitrary course/exercise/syllabus/lectures/tutor
text.

Non-goals: removing the wizard, the include-toggles, the RAG-mode selector,
`exercise_kind` / practice-problem support, or anything in `main_ui`.

## Background / current state

(From a full read-only inventory of `sandbox_ui/` and its `ui_core` touch points.)

- **DB:** `sandbox_ui/db/models.py` `Conversation` (lines 32-98) carries 10
  sandbox-only columns: `exercise_kind` (NOT NULL, default "exercise"),
  `course_enabled` / `syllabus_enabled` / `lectures_enabled` (NOT NULL, default
  True), `context_mode` (nullable), and the **five `custom_*` snapshots**
  (`custom_course_text`, `custom_exercise_text`, `custom_tutor_prompt`,
  `custom_syllabus_text`, `custom_lectures_text` — all **nullable**, models.py
  72-76). `main_ui`'s `Conversation` has none of these; `ui_core.db.models_common`
  documents that `Conversation` is deliberately NOT shared.
- **No Alembic in sandbox.** Schema is `Base.metadata.create_all` + a runtime
  `_reconcile_columns()` in `sandbox_ui/run_app.py` (20-58) that only ever
  `ALTER TABLE ... ADD COLUMN`. One-time transforms use hand-rolled boot steps
  (e.g. `_migrate_email_to_username`, run_app.py 61-119), wired in `on_startup`
  (run_app.py 122-139). There is no migration revision to drop.
- **Routes:** `sandbox_ui/routes/chat.py` reads the 5 custom fields
  (`course_custom`/`exercise_custom`/`tutor_custom`/`syllabus_custom`/
  `lectures_custom`, chat.py 182-188), has a "custom → set course/exercise/tutor
  to the literal `'custom'`" validation branch (chat.py 207-236), and threads
  them through `find_or_create_conversation` (256-274) and `stream_kwargs`
  (361-378). `sandbox_ui/routes/embed.py` exposes wizard-only endpoints
  `/api/context/options` (62-66 → `list_context_options`) and
  `/api/context/preview` (69-109 → `load_*_text`). `GET /embed` already ignores
  `?tutor=` and only takes `course`/`exercise` (embed.py 122-143).
- **Validation:** `sandbox_ui/routes/_validation.py` has wizard-only preview
  helpers `load_course_text` (110-115), `load_exercise_text` (118-122),
  `load_practice_text` (125-129), `load_tutor_text` (132-137),
  `load_syllabus_text` (140-145), `load_lectures_text` (148-154), consumed only
  by `/api/context/preview`. `list_context_options` (208-233) builds the
  built-in picker payload and is still needed. `_SELECTABLE_TUTORS = ("tutor_06",)`
  (198) is the tutor lock.
- **Bridge:** `sandbox_ui/services/tutor_bridge.py` module-level
  `build_assignment_text` (42-149) takes `course_text`/`exercise_text`/
  `syllabus_text`/`lectures_text` (custom-wins branches) plus toggles +
  `context_mode` + `exercise_kind`. `_render_custom_tutor_prompt` (152-176) and
  `_has_custom` (179-190) are custom-only. `SandboxTutorBridge` (193-266)
  overrides `prepare_ctx` (computes `has_custom`), `cache_key` (returns None on
  custom; else keys on toggles+kind+mode), `build_assignment_text`,
  `build_system_prompt` (custom-tutor-prompt branch), `turn_attachments` (skips
  figures for custom course/exercise). Module wrappers (271-373) expose the
  custom kwargs.
- **Service:** `sandbox_ui/services/conversation.py` packs the sandbox columns
  into `extra_fields` (65-76) and `_summarize_extra` (149-156) for the **generic**
  `ui_core.services.conversation` — which has **zero** hardcoded sandbox column
  names, so `ui_core` needs no change.
- **Frontend:** `sandbox_ui/static/js/chat.js` (1819 lines) — config defaults
  (6-25), wizard DOM refs (85-101), and the Create-context wizard core (820-1339)
  including `CUSTOM` sentinel (839), `fetchPreviewText` (842-869), step render,
  `finishCreate()` (1260-1339); send-payload wiring (1523-1539); event wiring
  (1788-1803). `sandbox_ui/templates/embed.html` — create-context button (7-20)
  and modal (48-65). `sandbox_ui/static/css/sandbox-extra.css` — `.create-custom`
  and friends, plus already-dead `.context-field`/`.context-checkbox`/`.lock-icon`.
- **Tests:** `sandbox_ui/routes/test_validation_practice.py` (list_context_options
  practice list) and `sandbox_ui/services/test_tutor_bridge_practice.py`
  (`build_assignment_text` exercise_kind) — both exercise KEPT features. No test
  touches the custom fields.

## Design

### 1. Frontend — strip custom-text from the wizard (keep built-in selection)

`sandbox_ui/static/js/chat.js`:
- Remove the `CUSTOM` sentinel option from the course / exercise / syllabus /
  lectures steps and delete the custom `<textarea>` (`create-custom`) rendering,
  `fetchPreviewText`, and the preview-into-textarea plumbing.
- Remove the **tutor step** entirely from `CREATE_STEPS`/`activeSteps()` (tutor is
  locked to tutor_06; its only remaining choice was the custom prompt).
- In `finishCreate()`, stop mapping `courseCustom`/`exerciseCustom`/`tutorCustom`/
  `syllabusCustom`/`lecturesCustom`.
- In the send handler (~1523-1539), stop sending `course_custom`/`exercise_custom`/
  `tutor_custom`/`syllabus_custom`/`lectures_custom`. Keep `exercise_kind`,
  `course_enabled`, `syllabus`, `lectures`, `context_mode`.
- Remove the custom-field config defaults (6-25).

`sandbox_ui/templates/embed.html`: keep the create-context button + modal (the
wizard still runs for built-in selection). No block removed unless it becomes
empty.

`sandbox_ui/static/css/sandbox-extra.css`: delete `.create-custom` (+ `:focus`,
`:read-only`) and the already-dead `.context-field`/`.context-label`/
`.context-checkbox`/`.lock-icon` rules. Keep `.create-step-body`,
`.create-actions`, `.context-select`, `.rag-toggle` (still used).

### 2. Routes

`sandbox_ui/routes/chat.py`:
- Delete the reads of the 5 custom fields (182-188).
- Delete the custom-context validation branch that sets course/exercise/tutor to
  `'custom'` and skips file validation (within 207-236) — every turn now
  references a real built-in course/exercise, so normal validation always runs.
- Drop the 5 custom kwargs from the `find_or_create_conversation` call (256-274)
  and from `stream_kwargs` (361-378). Keep `exercise_kind`, `include_course`/
  `include_syllabus`/`include_lectures`, `context_mode`.

`sandbox_ui/routes/embed.py`:
- Remove the `/api/context/preview` route (69-109) — it existed only to fill the
  custom textareas.
- Keep `/api/context/options` (built-in pickers) and `GET /embed` / `GET /`.

### 3. Validation

`sandbox_ui/routes/_validation.py`:
- Remove the preview-only helpers `load_course_text`, `load_exercise_text`,
  `load_practice_text`, `load_tutor_text`, `load_syllabus_text`,
  `load_lectures_text` (they had no consumer other than `/api/context/preview`).
- Keep `list_context_options`, `list_tutors` (returns `["tutor_06"]`),
  `course_has_syllabus`/`course_has_lectures`/`course_has_rag`, `validate_*`,
  `load_course_name`, and the `DEFAULT_*` constants.
- Verify (during implementation) that `list_context_options` does not call any
  removed helper; it currently uses `course_has_*` + `list_*`, not `load_*_text`.

### 4. Bridge

`sandbox_ui/services/tutor_bridge.py`:
- `build_assignment_text`: remove the `course_text`/`exercise_text`/
  `syllabus_text`/`lectures_text` params and their custom-wins branches; the
  course/syllabus/lectures blocks now come only from the on-disk built-in files
  gated by the include-toggles, still gated overall by `context_mode ==
  "full_context"`. Keep `exercise_kind` (exercise vs practice path) and the
  tutor-only solution key.
- Delete `_render_custom_tutor_prompt` and `_has_custom`.
- `SandboxTutorBridge`:
  - `prepare_ctx` → now always `has_custom=False`, making it identical to the base
    `TutorBridge.prepare_ctx`; **remove the override** (inherit base).
  - `build_system_prompt` → the custom-tutor-prompt branch is gone, leaving just
    `load_system_prompt(tutor, ...)` = the base; **remove the override**.
  - `turn_attachments` → the custom-course/exercise figure-skip is gone, leaving
    the base behavior; **remove the override**.
  - `cache_key` → drop the `has_custom → None` early return; keep the tuple keyed
    on toggles + `exercise_kind` + `context_mode` (still richer than the base key).
  - `build_assignment_text` override → keep (threads toggles/kind/mode).
- Module-level `get_tutor_reply`/`stream_tutor_reply` wrappers: drop the
  `course_text`/`exercise_text`/`syllabus_text`/`lectures_text`/
  `custom_tutor_prompt` kwargs. Keep `exercise_kind`, the three `include_*`,
  `context_mode`.

### 5. DB — drop the 5 columns via a boot step

`sandbox_ui/db/models.py`: remove the five `custom_*` column definitions from
`Conversation` (72-76).

`sandbox_ui/run_app.py`: add a one-time `_drop_custom_context_columns()` boot
step, modeled on `_migrate_email_to_username` (61-119), wired into `on_startup`
after `create_all`/`_reconcile_columns`. It must:
- Inspect the live table's columns (same introspection `_reconcile_columns`
  uses) and `ALTER TABLE conversations DROP COLUMN <name>` only for those of the
  five that actually exist — so it is idempotent and safe on a fresh DB (where
  `create_all` already omits them) and re-runs.
- Work on both SQLite (local dev; modern SQLite supports `DROP COLUMN`, but guard
  on existence rather than `IF EXISTS` which SQLite lacks) and Postgres (prod).
- Never touch the kept columns.

The stored custom-text snapshots are disposable testing data; dropping is
intentional and acceptable.

### 6. Service, tests, docs

`sandbox_ui/services/conversation.py`: drop the five `custom_*` kwargs from
`find_or_create_conversation` and from the `extra_fields` dict (65-76).
`_summarize_extra` did not include custom fields — unchanged. `ui_core` untouched.

Tests:
- `test_validation_practice.py` and `test_tutor_bridge_practice.py` — unaffected
  (they exercise `exercise_kind`/practice, which stays); confirm they still pass.
- Add a route-level test asserting that a `/api/chat` turn which includes a
  `course_custom` (or other custom_*) field **ignores** it — the conversation is
  created against the built-in course, and no custom text reaches the tutor. This
  guards the removal (the field is now inert, not honored).
- If any bridge unit test references the removed `build_assignment_text` custom
  params or `_render_custom_tutor_prompt`/`_has_custom`, update it.

Docs: rewrite `sandbox_ui/README.md` to drop the custom-context material (the
"Create context" wizard section's custom-text bullets, the `custom_*` column
list, the `/api/context/preview` API row, and the `*_custom` request-field
bullet), while keeping the wizard/toggle/mode/practice documentation.

### 7. What remains of `SandboxTutorBridge`

After this change the subclass keeps only `cache_key` and `build_assignment_text`
overrides (plus the module-level `build_assignment_text`). It still legitimately
differs from the base because sandbox has include-toggles + `exercise_kind` +
per-conversation `context_mode` selection that `main_ui` does not. Full
convergence to a bare wrapper is explicitly out of scope (it would require
dropping toggles/mode/practice — not wanted here).

## Testing

All offline. Run:
- `python -m ui_core.test_tutor_bridge`
- `python -m sandbox_ui.services.test_tutor_bridge_practice`
- `python -m pytest sandbox_ui/ -q`
- Full `python -m pytest -q` before finishing.

New coverage: the "custom field is ignored" route test (§6). Boot-step drop:
verify idempotence and that a fresh SQLite DB (no custom columns) is a no-op,
and that a DB with the columns has them removed after one boot.

## Files touched (anticipated)

- `sandbox_ui/static/js/chat.js` — remove custom-text wizard paths + tutor step + payload.
- `sandbox_ui/templates/embed.html` — only if a block empties out.
- `sandbox_ui/static/css/sandbox-extra.css` — remove dead custom/context CSS.
- `sandbox_ui/routes/chat.py` — remove custom reads/validation/threading.
- `sandbox_ui/routes/embed.py` — remove `/api/context/preview`.
- `sandbox_ui/routes/_validation.py` — remove `load_*_text` preview helpers.
- `sandbox_ui/services/tutor_bridge.py` — remove custom params/helpers, slim subclass.
- `sandbox_ui/services/conversation.py` — drop custom kwargs/extra_fields.
- `sandbox_ui/db/models.py` — remove 5 custom_* columns.
- `sandbox_ui/run_app.py` — add `_drop_custom_context_columns()` boot step.
- `sandbox_ui/README.md` — rewrite custom-context sections.
- Tests: new "custom ignored" route test; update any bridge test referencing removed custom API.

## Rollback

Removal is code-side; the boot-step drop is one-way for the live DB (data is
disposable testing data). To restore custom context, revert the commits — the
boot step is guarded on column existence so it will not error, but re-adding the
columns would require `_reconcile_columns` (which re-adds any model column), i.e.
restoring the ORM definitions.
