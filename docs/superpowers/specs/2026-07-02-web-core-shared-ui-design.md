# Shared Web Core (`web_core`) — Design

**Date:** 2026-07-02
**Status:** Approved (design), pending implementation plan
**Owner:** web/UI layer (`main_ui`, `sandbox_ui`, `database_ui`)

## Motivation

The Flask web apps duplicate their web layer. `main_ui` and `sandbox_ui` are
near-twins: every shared file has drifted apart (none are byte-identical), yet
most differ by only a handful of lines. A bug fix in `identity.py` or
`cookies.py` today must be hand-copied across apps. `database_ui` (read-only
review) shares the DB and conversation-read layer but has its own routes.

The domain layer is already centralized — the apps share `utils`, `tutor`, and
`rag` (18 / 6 / 4 imports). Only the **web layer** is duplicated. This design
extracts that layer into a shared `web_core` package, the same way `utils`
centralizes cross-cutting domain helpers.

## Current state (measured)

`main_ui` (~2043 py-lines) and `sandbox_ui` (~2701) have parallel structure:
`config.py`, `cookies.py`, `run_app.py`, `db/{models,session}.py`,
`routes/{chat,embed,history,identity,_validation}.py`,
`services/{conversation,images,students,tutor_bridge}.py`, `templates/embed.html`.

Per-file divergence (main_ui vs sandbox_ui, changed lines):

- **Tiny deltas (branding/DB-name/config):** `services/students.py` (2),
  `db/session.py` (4), `cookies.py` (6), `routes/identity.py` (6),
  `routes/history.py` (9), `services/images.py` (11).
- **Real per-app features (sandbox augmentations):**
  `services/tutor_bridge.py` (464 — RAG toggle + custom-context wizard),
  `routes/_validation.py` (147), `routes/chat.py` (146), `routes/embed.py` (71),
  `run_app.py` (70), `db/models.py` (50), `templates/embed.html` (39).

`database_ui` (~759 py-lines): read-only, shared-password auth, its own
`routes/database.py` and `services/conversations.py`, no chat pipeline.
`dashboard_ui` is trivial (2 files) and out of scope.

The apps are fully standalone (no cross-app imports) and are all **live on
Railway**, launched via `python -m <app>`.

## Decisions (from brainstorming)

- **Scope:** `main_ui` + `sandbox_ui` + `database_ui`. (`dashboard_ui` excluded.)
- **Depth:** full shared core with an `create_app()` app factory; each app
  collapses to a config object plus a few overrides.
- **Behavior:** **behavior-preserving** — every current per-app difference
  (intentional feature *and* accidental drift) is retained, expressed as config
  values or hooks. Each app behaves identically before/after. Cleanup of drift
  is explicitly deferred.

## Goals

- One `web_core` package owning the shared web layer; each app shrinks to a
  config + a few overrides.
- Behavior of all three apps unchanged, verifiable without API keys.
- Each migration phase independently shippable; all three apps stay deployable
  throughout.
- Deploy entrypoints (`python -m <app>`) and Alembic migrations unchanged.

## Non-goals

- Converging drift / cleaning up the diverged files to one behavior (deferred;
  behavior-preserving only).
- Touching `dashboard_ui` or the CLI `internal_ui` runners.
- Regenerating Alembic migrations or changing the DB schema.
- A live end-to-end smoke of each app (optional, deferred, needs API keys +
  the permission popup).

## Architecture

A new `web_core/` package (sibling of `utils/`):

```
web_core/
  __init__.py
  app_factory.py     # create_app(config, hooks) -> Flask; registers shared blueprints
  config.py          # AppConfig dataclass (values only)
  hooks.py           # AppHooks dataclass (behavior injection)
  cookies.py         # shared
  db/
    base.py          # shared declarative Base + shared model mixins/columns
    session.py       # shared engine/session factory (URL from config)
  routes/            # shared Flask blueprints
    identity.py
    history.py
    embed.py         # base; per-app tweaks via config/template vars
    chat.py          # base chat route; delegates to hooks.tutor_bridge
  services/
    conversation.py  # shared read/write
    images.py
    students.py
    tutor_bridge.py  # TutorBridge BASE class (captures main_ui behavior)
  templates/
    embed.html       # base template; branding via template vars
```

### Extension mechanism

`create_app(config: AppConfig, hooks: AppHooks) -> Flask`:

- **`AppConfig`** (plain values): `db_url`, brand color, app title, port,
  feature flags (`enable_rag`, `enable_create_context`, `read_only`), etc. Drives
  branding, DB target, and which optional blueprints/features are registered.
- **`AppHooks`** (behavior injection): a `tutor_bridge` instance (subclass of the
  `web_core` `TutorBridge` base), an optional `auth_gate` (for `database_ui`'s
  shared-password gate), and `extra_blueprints` (e.g. sandbox's create-context
  wizard).

The factory registers the shared blueprints, gates optional ones on config
flags, mounts `extra_blueprints`, and wires the `chat` blueprint to
`hooks.tutor_bridge`. The **behavioral** differences (the 464-line `tutor_bridge`
diff, chat specifics) live in the `TutorBridge` subclass and hook-mounted
blueprints — this is how "behavior-preserving" and "max dedup" coexist: the base
captures `main_ui`'s exact behavior; `sandbox_ui` subclasses to add RAG /
custom-context exactly as today.

### Per-app collapse

- **`main_ui`** → `AppConfig(brand=crimson, db=asktim)` + the default
  `TutorBridge`. Its behavior *is* the shared base.
- **`sandbox_ui`** → `AppConfig(brand=teal, db=asktim_test, enable_rag=True,
  enable_create_context=True)` + `SandboxTutorBridge(TutorBridge)` + a
  create-context blueprint via `extra_blueprints`.
- **`database_ui`** → `AppConfig(read_only=True)` + `auth_gate` hook + its own
  `database` blueprint; reuses `web_core.db` and the read side of
  `services/conversation`; registers **no** chat blueprint.

Each app package keeps `__init__.py` / `__main__.py` so `python -m <app>` and the
Railway/Docker entrypoints are unchanged.

## Migration phases (each independently shippable)

1. **Scaffold `web_core` + extract pure infra** — `cookies`, `db/session`, config
   base. Apps import from `web_core`; delete local copies.
2. **Shared services + read layer** — `conversation`, `images`, `students`, plus
   `database_ui`'s conversation-read.
3. **App factory + shared blueprints** — `create_app`, `AppConfig`/`AppHooks`,
   and the `identity` / `history` / `embed` blueprints; each `run_app` becomes a
   `create_app(...)` call. `database_ui` folds in here (no chat).
4. **Chat pipeline + `TutorBridge` base** — extract the shared base (main_ui
   behavior), `sandbox_ui` subclass, shared `chat` blueprint delegating to the
   hook.
5. **Collapse each app to config + overrides; delete the now-dead duplicated
   files.**

## Verification (behavior-preserving, no API keys)

- **URL-map snapshot:** before phase 1, capture each app's Flask URL map (rules +
  methods + endpoints). After every phase, assert it is unchanged. Cheap,
  offline, and catches accidental route/behavior drift.
- **Shared-module unit tests:** standalone repo-style tests (`web_core/test_*.py`)
  for `cookies`, `db/session`, `conversation`, `config`, factory wiring.
- **`TutorBridge` tests with a stub model:** inject a fake model via hooks so the
  `chat` / `tutor_bridge` logic is exercised with **zero** OpenAI/Anthropic calls.
- **Deferred (needs keys):** one live chat smoke per app, behind the API-key
  permission popup.

## Risks & mitigations

- **3 live Railway apps.** Each phase leaves all three runnable and deployable;
  behavior-preserving means responses should not change. Ship/verify per phase.
- **Alembic migrations** (main/sandbox) reference the model classes. Re-home the
  models into `web_core.db` **without changing `Base.metadata`** so existing
  migrations still resolve; do **not** regenerate migrations.
- **Import-path churn.** Internal imports move to `web_core.*`; the app packages
  remain as thin wrappers, so `python -m <app>`, Dockerfiles, and Railway configs
  are unaffected.
- **DB divergence** (`db/models.py` differs by 50 lines) — capture the union as a
  shared base with per-app additions via mixins/config, preserving each app's
  current tables/columns exactly.

## Success criteria

- `web_core` exists; `main_ui`, `sandbox_ui`, `database_ui` import their shared
  web layer from it; the duplicated per-app copies are deleted.
- Each app's Flask URL map is identical to its pre-refactor snapshot.
- `web_core` shared modules and the `TutorBridge` base/subclass have passing
  standalone tests (no API keys required).
- `python -m main_ui` / `sandbox_ui` / `database_ui` still start; Dockerfiles and
  Alembic migrations are unchanged.
