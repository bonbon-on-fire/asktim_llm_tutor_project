# ui_core Remaining Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish hoisting the remaining duplicated code across `main_ui` / `sandbox_ui` / `database_ui` into shared `ui_core` modules, so each app shrinks to config + its genuine differences.

**Architecture:** `ui_core` holds the shared web layer; each app keeps its own `Base`, `config.py`, and a thin set of overrides. Frontend assets move to a shared Flask static blueprint + Jinja base template; the backend collapses onto a `create_app(config, hooks)` factory with a `TutorBridge` base class the apps subclass. Every change is behavior-preserving and verified offline (no API keys).

**Tech Stack:** Python 3.12, Flask (blueprints, `ChoiceLoader`), SQLAlchemy 2.x, vanilla JS (ES modules), standalone `main()`+`_check()` tests (no pytest).

## Global Constraints

- **Behavior-preserving.** Rendered HTML, served static bytes, Flask URL map, and DB schema must not change. Prove it, don't assume it.
- **No API keys.** All verification is offline. A live chat turn (the only key-spending path) stays behind the existing PreToolUse permission popup and is deferred until the user approves.
- **Each phase independently shippable.** All three apps stay runnable/deployable after every phase (they are live on Railway).
- **Repo test convention:** standalone module with `main()` + `_check()`, non-zero exit on failure, run via `python -m <module>`. No pytest.
- **Commit trailer:** omit `Co-Authored-By: Claude`.
- **`database_ui` is read-only** and shares only what it genuinely uses — do not force it onto chat/tutor code.

## Status (already done — do NOT redo)

- Phase 1: `ui_core/cookies.py`, `ui_core/db/session.py` — shared, apps wrap. ✅
- Phase 2a: `ui_core/db/models_common.py` — `Message`/`Student`/`UploadedImage` mixins. ✅
- Quick wins: `curriculum/about_asktim.txt` + `utils.curriculum.load_about_asktim()`; `ui_core/services/images.py` + per-app wrappers. ✅

## Baseline artifact (build once, reuse every phase)

Before Phase 3, capture the invariants every later phase asserts against.

- [ ] **Capture the Flask URL map for each app** (rules, methods, endpoints) to `scratch/urlmap_<app>_before.txt`:

```python
# python -m <app>-urlmap style one-off; DATABASE_URL=sqlite for main/sandbox
from main_ui.run_app import app  # repeat per app
for r in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
    print(r.rule, sorted(r.methods), r.endpoint)
```

- [ ] **Capture served bytes of each static asset + rendered embed HTML** (curl each running app's `/`, `/static/css/chat.css`, `/static/js/chat.js`) to `scratch/*_before.html`. Diffs against these are the pass/fail gate for the frontend phases.

---

## Phase 3 — Shared frontend: `chat.css` (#2) + `embed.html` (#4)

**Goal:** One shared stylesheet and one base page template; apps keep only their deltas.

**Files:**
- Create: `ui_core/static/css/chat.css` (the shared base — start from `main_ui/static/css/chat.css`, which is byte-identical to `database_ui`'s)
- Create: `ui_core/static/__init__.py` is not needed; instead `ui_core/web/static_blueprint.py` — a `Blueprint("ui_core", __name__, static_folder=..., static_url_path="/ui-core")`
- Create: `ui_core/templates/base_chat.html` (blocks: `head`, `banner`, `sidebar_cta`, `composer`, `modals`, `scripts`)
- Create: `sandbox_ui/static/css/sandbox-extra.css` (sandbox's +160-line delta only)
- Modify: `main_ui/run_app.py`, `sandbox_ui/run_app.py`, `database_ui/run_app.py` — register the shared static blueprint + add `ui_core/templates` to a `ChoiceLoader`
- Modify: `main_ui/templates/embed.html`, `sandbox_ui/templates/embed.html` → `{% extends "base_chat.html" %}` + override only their differences
- Delete (end of phase): `main_ui/static/css/chat.css`, `database_ui/static/css/chat.css`, and the duplicated markup now in the base
- Test: `ui_core/web/test_static_blueprint.py`

**Interfaces:**
- Produces: `ui_core.web.static_blueprint.static_bp`; base template name `"base_chat.html"` reachable via every app's Jinja loader.

**Pre-work: confirm the CSS delta is purely additive.**
- [ ] **Step 1:** Diff sandbox vs main CSS; confirm sandbox is a superset (only additions). Run: `diff main_ui/static/css/chat.css sandbox_ui/static/css/chat.css` — expect only `>` lines. If any `<` line (a changed rule), record it: sandbox must override that rule in `sandbox-extra.css`, loaded AFTER the base.

**Shared static blueprint (TDD):**
- [ ] **Step 2 (failing test):** `ui_core/web/test_static_blueprint.py` builds a throwaway Flask app, registers `static_bp`, asserts `GET /ui-core/css/chat.css` returns 200 and the bytes equal `ui_core/static/css/chat.css` on disk.
- [ ] **Step 3:** Run it — FAIL (module missing).
- [ ] **Step 4:** Create `ui_core/static/css/chat.css` (move main's copy) and `ui_core/web/static_blueprint.py`.
- [ ] **Step 5:** Run it — PASS.
- [ ] **Step 6:** In each app's `run_app.py`, `app.register_blueprint(static_bp)`. Update the three `embed`/`index` templates' `<link>` to point at the shared URL; sandbox additionally links `sandbox-extra.css` after it.
- [ ] **Step 7 (assert byte-identity):** curl each app's chat CSS (shared + sandbox extra concatenated) and diff against `scratch/*_before`. main/database: identical. sandbox: base+extra must equal the old sandbox file (order matters — extra last).
- [ ] **Step 8:** Delete `main_ui/static/css/chat.css` and `database_ui/static/css/chat.css`. Re-run Step 7.
- [ ] **Step 9:** Commit.

**Base template (TDD):**
- [ ] **Step 10:** Author `ui_core/templates/base_chat.html` from `main_ui/templates/embed.html` with `{% block %}`s at each point sandbox diverges (banner, the Create-context CTA, the wizard modal, extra scripts).
- [ ] **Step 11:** Add `ChoiceLoader([app_loader, FileSystemLoader("ui_core/templates")])` in each `run_app.py`.
- [ ] **Step 12:** Rewrite `main_ui/templates/embed.html` to `{% extends "base_chat.html" %}` overriding only its (few) differences.
- [ ] **Step 13 (assert):** curl main `/`, diff rendered HTML against `scratch/main_before.html` — expect **zero** diff.
- [ ] **Step 14:** Rewrite `sandbox_ui/templates/embed.html` the same way (overrides: Create-context button + wizard modal + `sandbox-wizard` script tag). Diff against `scratch/sandbox_before.html` — zero diff.
- [ ] **Step 15:** Commit.

**Risk:** Low-medium. Whitespace differences in rendered HTML are the usual gotcha — the byte-diff gate catches them; normalize block indentation in the base until the diff is clean.

---

## Phase 4 — Backend keystone: `TutorBridge` base (#5) + app factory (#7)

This is the largest phase. Sub-phase it; each sub-phase ships independently.

### 4a — Shared conversation/history services (prerequisite for the factory)

**Files:**
- Create: `ui_core/services/conversation.py` — shared conversation create/lookup/list/append-message logic, parameterized by model classes (same pattern as `images.py`)
- Create: `ui_core/services/test_conversation.py`
- Modify: `main_ui/services/*`, `sandbox_ui/services/*` — thin wrappers binding their models
- Note: `sandbox_ui`'s `Conversation` carries 10 extra columns; the shared create/list signatures must accept an optional `extra_fields` dict so sandbox passes its wizard toggles without the base knowing about them.

**Tasks:** mirror the `images.py` refactor — write the shared parameterized module + isolated test on a local `Base`, then convert each app to a wrapper, asserting an ORM round-trip per app is unchanged.

### 4b — `TutorBridge` base + hooks

**Files:**
- Create: `ui_core/tutor_bridge.py` — base class: context assembly (`about_asktim + course + syllabus + lectures + exercise`), graph/stream caches, `get_tutor_reply` / `stream_tutor_reply` delegation to `tutor.run_tutor`
- Create: `ui_core/test_tutor_bridge.py` — inject a **stub model** via a hook; exercise assembly + caching with **zero** LLM calls
- Modify: `main_ui/services/tutor_bridge.py` → subclass with no overrides (it is the base behavior)
- Modify: `sandbox_ui/services/tutor_bridge.py` → subclass overriding `resolve_context_mode()`, `build_assignment_text()` (RAG + custom-text snapshots + include-toggles)

**Interfaces:**
- Produces: `class TutorBridge` with overridable hooks: `build_assignment_text(...)`, `resolve_context_mode(...)`, `make_model()` (stubbable in tests).

**Tasks (TDD):**
- [ ] Write `ui_core/test_tutor_bridge.py` first: a fake model returning a canned reply; assert (1) assembly output for a known course/exercise equals a golden string, (2) the cache key logic reuses a built graph, (3) `sandbox` subclass drops course/syllabus in `rag` mode. Run — FAIL.
- [ ] Extract the base from `main_ui`'s current `tutor_bridge.py` (the simpler one) into `ui_core/tutor_bridge.py`. Make `main_ui` a zero-override subclass. Run main's assembly golden — PASS.
- [ ] Port `sandbox_ui`'s extra behavior into overrides. Assert sandbox assembly goldens (full_context / rag / custom-text) match its current output. Run — PASS.
- [ ] Commit.

**Risk:** Medium. This is the LLM path, but assembly + caching are pure and fully testable with a stub model; no keys. The golden-string assertions are the safety net.

### 4c — App factory + shared blueprints

**Files:**
- Create: `ui_core/app_factory.py` — `create_app(config: AppConfig, hooks: AppHooks) -> Flask`
- Create: `ui_core/config_base.py` — `AppConfig` dataclass (ports, DB URL, cookie flags, feature flags: `has_rag`, `has_wizard`, read_only)
- Create: `ui_core/web/blueprints/{identity,history,embed,chat,images}.py` — shared route handlers delegating to services + the `TutorBridge` hook
- Create: `ui_core/web/test_app_factory.py` — build each app via the factory, assert URL map == baseline snapshot
- Modify: `main_ui/run_app.py`, `sandbox_ui/run_app.py`, `database_ui/run_app.py` → `app = create_app(AppConfig(...), AppHooks(...))`
- Modify: `*/config.py` → build the `AppConfig`; keep per-app env parsing

**Tasks (TDD):**
- [ ] Write `test_app_factory.py`: assert the URL map produced by `create_app` for each app’s config equals `scratch/urlmap_<app>_before.txt`. Run — FAIL.
- [ ] Move one blueprint at a time (start with `identity`, then `history`, `images`, `embed`, `chat`) from each app's `routes/` into `ui_core/web/blueprints/`, registering via the factory. After each blueprint moves, re-run the URL-map assertion + curl-diff the affected routes. `database_ui` registers only `identity`+a read blueprint (no chat).
- [ ] Collapse each `run_app.py` to a `create_app(...)` call. Re-assert URL maps.
- [ ] Commit per blueprint (each is independently shippable).

**Risk:** Medium. The URL-map snapshot + per-route curl-diff catch drift. Move one blueprint per commit so a regression is bisectable.

---

## Phase 5 — Frontend JS: `chat.js` module split (#3)

**Deferred to last — highest risk (behavioral JS on live chat).**

**Files:**
- Create: `ui_core/static/js/chat-core.js` — shared: chat send/stream loop, history render, identity/cookie modal, image upload
- Create: `sandbox_ui/static/js/sandbox-wizard.js` — sandbox-only create/edit-context wizard (the ~640-line delta)
- Modify: the base template `scripts` block to load `chat-core.js`; sandbox overrides to also load `sandbox-wizard.js`
- Delete: `main_ui/static/js/chat.js`, `sandbox_ui/static/js/chat.js`

**Tasks:**
- [ ] Reconcile the two files function-by-function: identify the true shared core (they diverged over 707 lines; sandbox is a superset + wizard). Extract shared into `chat-core.js` verbatim.
- [ ] Move sandbox-only functions into `sandbox-wizard.js`; expose the small surface it calls on the core via a namespace or module export.
- [ ] Manual smoke via Playwright against the running apps (offline: page loads, sidebar toggles, modal opens, composer enables) — no chat turn (that needs a key).
- [ ] Deferred, behind the key popup: one live chat turn per app to confirm streaming still works.
- [ ] Commit.

**Risk:** Medium-high. No cheap byte-diff gate (behavior, not bytes). Do it last, in its own PR, with the Playwright smoke as the offline gate.

---

## Phase 6 — Collapse & delete dead files

- [ ] Remove any now-unused per-app modules (old `routes/`, dead `config` helpers) surfaced by Phases 3–5.
- [ ] Grep for dangling imports; run every `ui_core/**/test_*.py` + each app's import smoke.
- [ ] Final whole-branch review (superpowers:requesting-code-review) before merge.

---

## Verification summary (offline, per phase)

| Invariant | Gate |
|---|---|
| Flask URL map unchanged | assert against `scratch/urlmap_<app>_before.txt` |
| Served static bytes unchanged | curl + diff vs `scratch/*_before` |
| Rendered embed HTML unchanged | curl `/` + diff vs baseline |
| DB schema unchanged | `CreateTable`/`CreateIndex` DDL diff (as in Phase 2a) |
| Tutor assembly unchanged | golden-string tests with a stub model |
| Shared logic correct | `ui_core/**/test_*.py` standalone suites |
| Live chat (deferred) | one turn/app, behind the API-key popup, only on user approval |

## Suggested execution order

1. Phase 3 (frontend static + templates) — low risk, immediate "stop editing 3 files" payoff.
2. Phase 4a → 4b → 4c (backend keystone) — ship per sub-phase.
3. Phase 5 (JS split) — last, own PR.
4. Phase 6 (cleanup) + whole-branch review.
