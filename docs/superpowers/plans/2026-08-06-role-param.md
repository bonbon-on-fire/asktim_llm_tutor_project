# `role` Param Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `role` URL query param (default `tutor`) to both web apps that selects which prompt folder + default prompt the assistant uses; `role=tutor` keeps today's `tutor_07` behavior, `role=ta` is scaffolded to 404 until a `ta/prompts/` folder is added.

**Architecture:** A shared role registry (`tutor/roles.py`) maps each role to a prompt folder + default prompt and is the single source of truth. `load_system_prompt` gains a backward-compatible `prompts_dir` arg; the web bridge resolves the folder from the (unique) prompt name via the registry, so no DB migration or persisted `role` column is needed. Both `main_ui` and `sandbox_ui` gain identical `role` plumbing in their `_validation.py` / `embed.py` / `chat.py` / `chat.js`.

**Tech Stack:** Python 3.12, Flask, plain JS. Tests are self-contained scripts run with `python -m <module>` (repo convention — no pytest).

## Global Constraints

- Commits use Conventional Commits (`type(scope): subject`). **Do NOT add a `Co-Authored-By: Claude` trailer.**
- Run test scripts from the repo root `d:\asktim_llm_tutor_project` (they import top-level packages). On Git Bash set `PYTHONPATH=/d/asktim_llm_tutor_project` if needed.
- Keep `main_ui` and `sandbox_ui` at full parity — every route/validation/frontend change lands in both.
- `DEFAULT_ROLE = "tutor"`; the `tutor` role's default prompt is `"tutor_07"`.
- `role=ta` and any unknown role must 404 (the `ta` registry entry stays commented out — no TA prompt content is shipped).
- When editing `sandbox_ui/static/js/chat.js`, bump the `?v=` cache-buster in `sandbox_ui/templates/embed.html` (currently `v='22'`). Same rule for `main_ui` (`v='6'`).

---

### Task 1: Role registry (`tutor/roles.py`)

**Files:**
- Create: `tutor/roles.py`
- Test: `tutor/test_roles.py`

**Interfaces:**
- Produces:
  - `DEFAULT_ROLE: str` (`"tutor"`)
  - `@dataclass(frozen=True) class Role: name: str; prompts_dir: Path; default_prompt: str`
  - `ROLES: dict[str, Role]`
  - `get_role(name: str | None) -> Role | None`
  - `prompts_dir_for_prompt(prompt_name: str) -> Path | None`

- [ ] **Step 1: Write the failing test**

Create `tutor/test_roles.py`:

```python
"""Unit checks for the role registry.

Run:
    python -m tutor.test_roles
"""
from __future__ import annotations

from pathlib import Path

from tutor.roles import (
    DEFAULT_ROLE,
    ROLES,
    get_role,
    prompts_dir_for_prompt,
)


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    ok &= _check("default role is tutor", DEFAULT_ROLE == "tutor", DEFAULT_ROLE)

    tutor = get_role("tutor")
    ok &= _check("tutor role registered", tutor is not None)
    ok &= _check("tutor default prompt is tutor_07",
                 tutor is not None and tutor.default_prompt == "tutor_07")
    ok &= _check("tutor prompts_dir exists",
                 tutor is not None and tutor.prompts_dir.is_dir(), tutor.prompts_dir)

    ok &= _check("unknown role -> None", get_role("ta") is None)
    ok &= _check("None role -> None", get_role(None) is None)
    ok &= _check("ta not registered (scaffold only)", "ta" not in ROLES)

    d = prompts_dir_for_prompt("tutor_07")
    ok &= _check("reverse lookup finds tutor folder",
                 d is not None and (d / "tutor_07.txt").is_file(), d)
    ok &= _check("reverse lookup unknown prompt -> None",
                 prompts_dir_for_prompt("does_not_exist") is None)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m tutor.test_roles`
Expected: FAIL — `ModuleNotFoundError: No module named 'tutor.roles'`

- [ ] **Step 3: Write minimal implementation**

Create `tutor/roles.py`:

```python
"""Role registry: the single source of truth mapping an assistant *role* to its
prompt folder and default prompt.

A role decides which prompt family the web apps use. ``tutor`` reads
``tutor/prompts/`` with default ``tutor_07`` (today's behavior). Additional
roles (e.g. a teaching assistant ``ta`` reading ``ta/prompts/``) are added by
creating the folder and registering an entry below — until then the role is
unknown and the web layer 404s on it.

Both ``main_ui`` and ``sandbox_ui`` import from here so they stay in lockstep.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Role:
    """A named assistant role: which prompt folder and default prompt to use."""

    name: str
    prompts_dir: Path
    default_prompt: str


DEFAULT_ROLE = "tutor"

# Only roles that are ready to serve appear here. To add the TA role later:
# create ``ta/prompts/ta_01.txt`` (+ variants) and uncomment the entry below.
ROLES: dict[str, Role] = {
    "tutor": Role("tutor", _REPO_ROOT / "tutor" / "prompts", "tutor_07"),
    # "ta": Role("ta", _REPO_ROOT / "ta" / "prompts", "ta_01"),
}


def get_role(name: str | None) -> Role | None:
    """Return the :class:`Role` for *name*, or ``None`` if unknown/unregistered."""
    return ROLES.get(name) if name else None


def prompts_dir_for_prompt(prompt_name: str) -> Path | None:
    """Return the registered ``prompts_dir`` whose folder owns ``<prompt_name>.txt``.

    Prompt names are unique per role (``tutor_*`` vs ``ta_*``), so at most one
    registered role matches. Returns ``None`` when no registered role owns the
    prompt — callers then fall back to the default tutor folder.
    """
    for role in ROLES.values():
        if (role.prompts_dir / f"{prompt_name}.txt").is_file():
            return role.prompts_dir
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m tutor.test_roles`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tutor/roles.py tutor/test_roles.py
git commit -m "feat(tutor): add role registry (tutor role, ta scaffold)"
```

---

### Task 2: `load_system_prompt` gains `prompts_dir`

**Files:**
- Modify: `tutor/run_tutor.py` (function `load_system_prompt`, ~lines 71-101)
- Test: `tutor/test_load_system_prompt_dir.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `load_system_prompt(prompt_name="tutor_01", assignment_override=None, prompts_dir=None)` — when `prompts_dir` is `None`, uses the existing `PROMPTS_DIR` (`tutor/prompts/`); otherwise reads `<prompts_dir>/<prompt_name>.txt`.

- [ ] **Step 1: Write the failing test**

Create `tutor/test_load_system_prompt_dir.py`:

```python
"""Checks that load_system_prompt honors an explicit prompts_dir.

Run:
    python -m tutor.test_load_system_prompt_dir
"""
from __future__ import annotations

from pathlib import Path

from tutor.run_tutor import PROMPTS_DIR, load_system_prompt


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True

    # Default folder (prompts_dir=None) still works and honors assignment override.
    default_text = load_system_prompt("tutor_07", assignment_override="ZZZMARKER")
    ok &= _check("default dir loads tutor_07", bool(default_text))
    ok &= _check("assignment override applied", "ZZZMARKER" in default_text)

    # Explicit prompts_dir pointing at the same folder yields the same content.
    explicit_text = load_system_prompt(
        "tutor_07", assignment_override="ZZZMARKER", prompts_dir=PROMPTS_DIR
    )
    ok &= _check("explicit dir matches default", explicit_text == default_text)

    # A prompts_dir that lacks the file raises FileNotFoundError.
    missing = False
    try:
        load_system_prompt("tutor_07", prompts_dir=Path(__file__).resolve().parent)
    except FileNotFoundError:
        missing = True
    ok &= _check("missing file in explicit dir raises", missing)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m tutor.test_load_system_prompt_dir`
Expected: FAIL — `TypeError: load_system_prompt() got an unexpected keyword argument 'prompts_dir'`

- [ ] **Step 3: Write minimal implementation**

In `tutor/run_tutor.py`, replace the `load_system_prompt` signature + body head. Change the signature to add `prompts_dir` and use a `base_dir` local:

```python
def load_system_prompt(
    prompt_name: str = "tutor_01",
    assignment_override: str | None = None,
    prompts_dir: "Path | None" = None,
) -> str:
    """
    Load a tutor system prompt from ``<prompts_dir>/<prompt_name>.txt``.

    *prompts_dir* defaults to ``tutor/prompts/`` (``PROMPTS_DIR``); pass a
    different folder to load a non-tutor role's prompt (see ``tutor.roles``).
    If *assignment_override* is provided, the ``<Assignment>...</Assignment>``
    block inside the prompt is replaced with the override text.
    """
    base_dir = prompts_dir if prompts_dir is not None else PROMPTS_DIR
    path = base_dir / f"{prompt_name}.txt"
    if not path.exists():
        available = sorted(p.stem for p in base_dir.glob("*.txt"))
        raise FileNotFoundError(
            f"Tutor prompt '{prompt_name}' not found at {path}.\n"
            f"Available prompts: {available}"
        )
    text = path.read_text(encoding="utf-8")
```

Leave the rest of the function (the `assignment_override` regex block and
`return text.strip()`) unchanged. `Path` is already imported in this module.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m tutor.test_load_system_prompt_dir`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add tutor/run_tutor.py tutor/test_load_system_prompt_dir.py
git commit -m "feat(tutor): load_system_prompt accepts explicit prompts_dir"
```

---

### Task 3: Bridge resolves prompt folder from the registry

**Files:**
- Modify: `ui_core/tutor_bridge.py` (method `build_system_prompt`, ~lines 338-347; imports near top)
- Test: `ui_core/test_build_system_prompt_role.py`

**Interfaces:**
- Consumes: `tutor.roles.prompts_dir_for_prompt`, `tutor.run_tutor.load_system_prompt(..., prompts_dir=...)`.
- Produces: `TutorBridge().build_system_prompt(tutor, assignment_text, course="")` unchanged signature; now resolves the folder for `tutor` via the registry (falls back to the default tutor folder when unknown).

- [ ] **Step 1: Write the failing test**

Create `ui_core/test_build_system_prompt_role.py`:

```python
"""Checks that the bridge resolves the prompt folder via the role registry.

Run:
    python -m ui_core.test_build_system_prompt_role
"""
from __future__ import annotations

from ui_core.tutor_bridge import TutorBridge


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    bridge = TutorBridge()

    # tutor_07 is owned by the tutor role -> loads from tutor/prompts and the
    # assignment override is applied, proving the right file was read.
    prompt = bridge.build_system_prompt("tutor_07", "ZZZMARKER", course="")
    ok &= _check("build_system_prompt loads tutor_07", bool(prompt))
    ok &= _check("assignment override present", "ZZZMARKER" in prompt)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m ui_core.test_build_system_prompt_role`
Expected: PASS is NOT guaranteed yet — this test passes on the current code too (it's a regression guard). Run it now and confirm it PASSES against the pre-change bridge; that proves the test is valid before you change the wiring. (If it errors on import, fix the import path first.)

Note: this task has no red-phase because it guards existing behavior through a refactor. Proceed to Step 3.

- [ ] **Step 3: Write the implementation**

In `ui_core/tutor_bridge.py`, add the registry import near the other `tutor`
imports (the module already imports `load_system_prompt` from `tutor.run_tutor`):

```python
from tutor.roles import prompts_dir_for_prompt
```

Replace the body of `build_system_prompt`:

```python
    def build_system_prompt(self, tutor: str, assignment_text: str, course: str = "", **ctx) -> str:
        """Wrap *assignment_text* into the full system prompt for *tutor*.

        The prompt's folder is resolved from the role registry by prompt name
        (``tutor_*`` -> tutor/prompts, future ``ta_*`` -> ta/prompts). An
        unrecognized prompt name falls back to the default tutor folder.

        When *course* ships a ``curriculum/<course>/tutor_rules.txt``, its
        course-specific rules are appended to the base prompt (see
        ``utils.curriculum.append_course_tutor_rules``); otherwise the base prompt
        is returned unchanged.
        """
        prompts_dir = prompts_dir_for_prompt(tutor)  # None -> load_system_prompt uses tutor/prompts
        base = load_system_prompt(tutor, assignment_override=assignment_text, prompts_dir=prompts_dir)
        return append_course_tutor_rules(base, course)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m ui_core.test_build_system_prompt_role`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add ui_core/tutor_bridge.py ui_core/test_build_system_prompt_role.py
git commit -m "feat(ui_core): resolve prompt folder from role registry in bridge"
```

---

### Task 4: `main_ui` role param (validators, routes, frontend)

**Files:**
- Modify: `main_ui/routes/_validation.py` (add role helpers)
- Modify: `main_ui/routes/embed.py` (read/validate/resolve role; add to `tutor_config`)
- Modify: `main_ui/routes/chat.py` (read/validate role; resolve default prompt for new convos)
- Modify: `main_ui/static/js/chat.js` (send `role` in both payloads)
- Modify: `main_ui/templates/embed.html` (`v='6'` -> `v='7'`)
- Test: `main_ui/routes/test_role_param.py`

**Interfaces:**
- Consumes: `tutor.roles.DEFAULT_ROLE`, `tutor.roles.get_role`.
- Produces (in `_validation.py`):
  - `DEFAULT_ROLE` (re-exported from `tutor.roles`)
  - `validate_role(role) -> dict | None`
  - `role_default_prompt(role) -> str | None`

- [ ] **Step 1: Write the failing test**

Create `main_ui/routes/test_role_param.py`:

```python
"""Flask test-client checks for the role param in main_ui.

Run:
    python -m main_ui.routes.test_role_param
"""
from __future__ import annotations

from main_ui.run_app import app
from main_ui.routes._validation import (
    DEFAULT_ROLE,
    role_default_prompt,
    validate_role,
)


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()

    ok &= _check("DEFAULT_ROLE is tutor", DEFAULT_ROLE == "tutor", DEFAULT_ROLE)
    ok &= _check("validate_role(tutor) ok", validate_role("tutor") is None)
    ok &= _check("validate_role(ta) fails", validate_role("ta") is not None)
    ok &= _check("validate_role(bogus) fails", validate_role("bogus") is not None)
    ok &= _check("role_default_prompt(tutor) == tutor_07",
                 role_default_prompt("tutor") == "tutor_07")

    # /embed default role renders and carries role=tutor in the page config.
    r = client.get("/embed?course=supply_chain_design&exercise=1")
    ok &= _check("/embed default role 200", r.status_code == 200, r.status_code)
    ok &= _check("/embed config has role tutor",
                 b'"role": "tutor"' in r.data or b'"role":"tutor"' in r.data)

    # explicit role=tutor renders; role=ta and role=bogus 404.
    ok &= _check("role=tutor 200",
                 client.get("/embed?course=supply_chain_design&exercise=1&role=tutor").status_code == 200)
    ok &= _check("role=ta 404",
                 client.get("/embed?course=supply_chain_design&exercise=1&role=ta").status_code == 404)
    ok &= _check("role=bogus 404",
                 client.get("/embed?course=supply_chain_design&exercise=1&role=bogus").status_code == 404)

    # bare host renders with role=tutor even though course is empty.
    root = client.get("/")
    ok &= _check("/ has role tutor",
                 b'"role": "tutor"' in root.data or b'"role":"tutor"' in root.data)

    # chat send with bad role 404s.
    bad = client.post("/api/chat", json={"text": "hi", "course": "supply_chain_design",
                                         "exercise": "1", "role": "bogus"})
    ok &= _check("chat role=bogus 404", bad.status_code == 404, bad.status_code)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m main_ui.routes.test_role_param`
Expected: FAIL — `ImportError: cannot import name 'role_default_prompt'`

- [ ] **Step 3a: Add role helpers to `_validation.py`**

In `main_ui/routes/_validation.py`, add near the top imports:

```python
from tutor.roles import DEFAULT_ROLE, get_role
```

And add these functions (next to `validate_tutor`):

```python
def validate_role(role) -> dict | None:
    """Return None if *role* names a registered role, else a failure dict."""
    if not role:
        return _err("role", role, "missing")
    if get_role(role) is None:
        return _err("role", role, "no such role")
    return None


def role_default_prompt(role) -> str | None:
    """Return the default prompt name for *role* (e.g. 'tutor' -> 'tutor_07')."""
    r = get_role(role)
    return r.default_prompt if r else None
```

(`DEFAULT_ROLE` is now importable from this module via the re-export above.)

- [ ] **Step 3b: Wire role into `embed.py`**

In `main_ui/routes/embed.py`:

Update the import block to add the role helpers:

```python
from main_ui.routes._validation import (
    DEFAULT_EXERCISE,
    DEFAULT_ROLE,
    DEFAULT_TUTOR,
    load_course_name,
    resolve_embed_selection,
    role_default_prompt,
    validate_course,
    validate_role,
    validate_tutor,
)
```

Add a `role` param to `_render_embed` and include it in `tutor_config`:

```python
def _render_embed(*, course: str, exercise: str, tutor: str, exercise_kind: str = "exercise", role: str = DEFAULT_ROLE):
    """Render ``embed.html`` for the given course/exercise|practice/tutor/role context."""
    tutor_config = {
        "course": course,
        "exercise": exercise,
        "tutor": tutor,
        "role": role,
        "exercise_kind": exercise_kind,
        "labels": load_ui_labels(course),
    }
    has_email = bool(read_username_cookie(request))
    return render_template(
        "embed.html",
        course=course,
        exercise=exercise,
        tutor=tutor,
        course_name=load_course_name(course),
        tutor_config=tutor_config,
        has_email=has_email,
    )
```

Rewrite `index()` and the head of `embed()` so role is resolved first (an
invalid role 404s even when the course is empty):

```python
@embed_bp.get("/")
def index():
    """Default entry point for bare host URLs (e.g. Railway public domain).

    No default course: render an empty course context so the page loads but the
    first chat send surfaces the error (see module docstring). Role defaults to
    tutor.
    """
    return _render_embed(
        course="", exercise="", tutor=role_default_prompt(DEFAULT_ROLE), role=DEFAULT_ROLE
    )


@embed_bp.get("/embed")
def embed():
    """Resolve role + course + exercise|practice from query params, validate, and render."""
    role = request.args.get("role") or DEFAULT_ROLE
    err = validate_role(role)
    if err:
        return _bad_param(err)
    tutor = role_default_prompt(role)

    course = request.args.get("course")
    if not course:
        return _render_embed(course="", exercise="", tutor=tutor, role=role)

    err = validate_course(course)
    if err:
        return _bad_param(err)

    number, kind, err = resolve_embed_selection(
        course, request.args.get("exercise"), request.args.get("practice"), DEFAULT_EXERCISE
    )
    if err:
        return _bad_param(err)

    err = validate_tutor(tutor)
    if err:
        return _bad_param(err)

    return _render_embed(course=course, exercise=number, tutor=tutor, exercise_kind=kind, role=role)
```

(The `tutor` local is no longer hardcoded to `DEFAULT_TUTOR`; it comes from the
role. `DEFAULT_TUTOR` is still imported for other references — leave the import.)

- [ ] **Step 3c: Wire role into `chat.py`**

In `main_ui/routes/chat.py`, update the `_validation` import to add
`DEFAULT_ROLE`, `role_default_prompt`, `validate_role`:

```python
from main_ui.routes._validation import (
    DEFAULT_ROLE,
    DEFAULT_TUTOR,
    role_default_prompt,
    validate_course,
    validate_role,
    validate_selection,
    validate_tutor,
)
```

Replace the tutor-resolution block (currently `tutor = DEFAULT_TUTOR` with its
comment) with role resolution:

```python
    course = src.get("course")
    exercise = src.get("exercise")
    raw_kind = src.get("exercise_kind")
    exercise_kind = "practice" if str(raw_kind).strip().lower() == "practice" else "exercise"
    # The role selects the prompt family; each role is locked to its default
    # prompt (production keeps its single-prompt lock). Unknown role -> 404.
    role = src.get("role") or DEFAULT_ROLE
    err = validate_role(role)
    if err:
        return _bad_param(err)
    tutor = role_default_prompt(role)

    err = validate_course(course)
    if err:
        return _bad_param(err)
    err = validate_selection(course, exercise, exercise_kind)
    if err:
        return _bad_param(err)
    err = validate_tutor(tutor)
    if err:
        return _bad_param(err)
```

(For an existing conversation, `find_or_create_conversation` returns it with its
stored `tutor_prompt`, and the stream still uses `convo.tutor_prompt` — so role
only sets the prompt for NEW conversations. No further change needed.)

- [ ] **Step 3d: Send role from `chat.js` + bump cache-buster**

In `main_ui/static/js/chat.js`, add role to both payloads. In the multipart
branch, after `form.append("tutor", config.tutor);` add:

```javascript
      form.append("role", config.role);
```

In the JSON branch, in the `payload` object after `tutor: config.tutor,` add:

```javascript
        role: config.role,
```

In `main_ui/templates/embed.html`, bump the cache-buster:

```jinja
{% block chat_js_src %}{{ url_for('static', filename='js/chat.js', v='7') }}{% endblock %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m main_ui.routes.test_role_param`
Expected: all PASS

Also run the earlier regressions:
Run: `python -m main_ui.routes.test_embed_no_course`
Run: `python -m main_ui.routes.test_embed_practice`
Expected: PASS / (embed_practice may SKIP the practice leg — that's fine)

- [ ] **Step 5: Commit**

```bash
git add main_ui/routes/_validation.py main_ui/routes/embed.py main_ui/routes/chat.py main_ui/static/js/chat.js main_ui/templates/embed.html main_ui/routes/test_role_param.py
git commit -m "feat(main_ui): add role query param (default tutor)"
```

---

### Task 5: `sandbox_ui` role param (parity with main_ui)

**Files:**
- Modify: `sandbox_ui/routes/_validation.py` (add role helpers)
- Modify: `sandbox_ui/routes/embed.py` (read/validate/resolve role; add to `tutor_config`)
- Modify: `sandbox_ui/routes/chat.py` (read/validate role inside the new-convo block; resolve default prompt)
- Modify: `sandbox_ui/static/js/chat.js` (send `role` in the shared `fields` object)
- Modify: `sandbox_ui/templates/embed.html` (`v='22'` -> `v='23'` on the chat.js include)
- Test: `sandbox_ui/routes/test_role_param.py`

**Interfaces:**
- Same helpers as Task 4, in `sandbox_ui/routes/_validation.py`:
  `DEFAULT_ROLE`, `validate_role`, `role_default_prompt`.

- [ ] **Step 1: Write the failing test**

Create `sandbox_ui/routes/test_role_param.py` (mirror of the main_ui test):

```python
"""Flask test-client checks for the role param in sandbox_ui.

Run:
    python -m sandbox_ui.routes.test_role_param
"""
from __future__ import annotations

from sandbox_ui.run_app import app
from sandbox_ui.routes._validation import (
    DEFAULT_ROLE,
    role_default_prompt,
    validate_role,
)


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()

    ok &= _check("DEFAULT_ROLE is tutor", DEFAULT_ROLE == "tutor", DEFAULT_ROLE)
    ok &= _check("validate_role(tutor) ok", validate_role("tutor") is None)
    ok &= _check("validate_role(ta) fails", validate_role("ta") is not None)
    ok &= _check("role_default_prompt(tutor) == tutor_07",
                 role_default_prompt("tutor") == "tutor_07")

    r = client.get("/embed?course=supply_chain_design&exercise=1")
    ok &= _check("/embed default role 200", r.status_code == 200, r.status_code)
    ok &= _check("/embed config has role tutor",
                 b'"role": "tutor"' in r.data or b'"role":"tutor"' in r.data)

    ok &= _check("role=ta 404",
                 client.get("/embed?course=supply_chain_design&exercise=1&role=ta").status_code == 404)
    ok &= _check("role=bogus 404",
                 client.get("/embed?course=supply_chain_design&exercise=1&role=bogus").status_code == 404)

    root = client.get("/")
    ok &= _check("/ has role tutor",
                 b'"role": "tutor"' in root.data or b'"role":"tutor"' in root.data)

    bad = client.post("/api/chat", json={"text": "hi", "course": "supply_chain_design",
                                         "exercise": "1", "role": "bogus"})
    ok &= _check("chat role=bogus 404", bad.status_code == 404, bad.status_code)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m sandbox_ui.routes.test_role_param`
Expected: FAIL — `ImportError: cannot import name 'role_default_prompt'`

- [ ] **Step 3a: Add role helpers to sandbox `_validation.py`**

In `sandbox_ui/routes/_validation.py`, add the import:

```python
from tutor.roles import DEFAULT_ROLE, get_role
```

And add (next to `validate_tutor`):

```python
def validate_role(role) -> dict | None:
    """Return None if *role* names a registered role, else a failure dict."""
    if not role:
        return _err("role", role, "missing")
    if get_role(role) is None:
        return _err("role", role, "no such role")
    return None


def role_default_prompt(role) -> str | None:
    """Return the default prompt name for *role* (e.g. 'tutor' -> 'tutor_07')."""
    r = get_role(role)
    return r.default_prompt if r else None
```

Note: confirm sandbox's `_err` helper exists (it does — same shape as main_ui).
If `_err` is named differently, match the local name.

- [ ] **Step 3b: Wire role into sandbox `embed.py`**

Update the import to add `DEFAULT_ROLE, role_default_prompt, validate_role`.

Add `role` to `_render_embed` and `tutor_config` (note sandbox uses the
`exerciseKind` key — keep it; add `role`):

```python
def _render_embed(*, course: str, exercise: str, tutor: str, exercise_kind: str = "exercise", role: str = DEFAULT_ROLE):
    """Render the embed.html chat widget for the given course/exercise|practice/tutor/role context."""
    tutor_config = {
        "course": course,
        "exercise": exercise,
        "tutor": tutor,
        "role": role,
        "exerciseKind": exercise_kind,
    }
    has_email = bool(read_username_cookie(request))
    return render_template(
        "embed.html",
        course=course,
        exercise=exercise,
        tutor=tutor,
        course_name=load_course_name(course),
        tutor_config=tutor_config,
        has_email=has_email,
    )
```

Rewrite `index()` and `embed()` head to resolve role first:

```python
@embed_bp.get("/")
def index():
    """Default entry point for bare host URLs (e.g. Railway public domain).

    No default course: render an empty course context (page loads, first send
    404s). Role defaults to tutor. Matches main_ui.
    """
    return _render_embed(
        course="", exercise="", tutor=role_default_prompt(DEFAULT_ROLE), role=DEFAULT_ROLE
    )


@embed_bp.get("/embed")
def embed():
    """Render the chat widget from query params (exercise XOR practice), validating the resolved value."""
    role = request.args.get("role") or DEFAULT_ROLE
    err = validate_role(role)
    if err:
        return _bad_param(err)
    tutor = role_default_prompt(role)

    course = request.args.get("course")
    if not course:
        return _render_embed(course="", exercise="", tutor=tutor, role=role)

    err = validate_course(course)
    if err:
        return _bad_param(err)

    number, kind, err = resolve_embed_selection(
        course, request.args.get("exercise"), request.args.get("practice"), DEFAULT_EXERCISE
    )
    if err:
        return _bad_param(err)

    err = validate_tutor(tutor)
    if err:
        return _bad_param(err)

    return _render_embed(course=course, exercise=number, tutor=tutor, exercise_kind=kind, role=role)
```

- [ ] **Step 3c: Wire role into sandbox `chat.py`**

Update the `_validation` import to add `DEFAULT_ROLE, role_default_prompt,
validate_role`.

Replace the `tutor = DEFAULT_TUTOR` block (~line 148) with role resolution:

```python
    # The role selects the prompt family; each role is locked to its default
    # prompt (mirrors main_ui). Unknown role -> 404 (validated below, new
    # conversations only).
    role = src.get("role") or DEFAULT_ROLE
    tutor = role_default_prompt(role) or DEFAULT_TUTOR
```

Then, inside the existing `if convo_id is None:` validation block, add the role
check alongside the others:

```python
    if convo_id is None:
        err = validate_role(role)
        if err:
            return _bad_param(err)

        err = validate_course(course)
        if err:
            return _bad_param(err)

        err = validate_selection(course, exercise, exercise_kind)
        if err:
            return _bad_param(err)

        err = validate_tutor(tutor)
        if err:
            return _bad_param(err)
```

(Placing `role = ...` / `tutor = role_default_prompt(role) or DEFAULT_TUTOR`
before this block means an unknown role for a NEW conversation resolves `tutor`
to `DEFAULT_TUTOR` but is then rejected by `validate_role` -> 404, matching the
test. Continuations skip validation and use the stored `tutor_prompt`.)

- [ ] **Step 3d: Send role from sandbox `chat.js` + bump cache-buster**

In `sandbox_ui/static/js/chat.js`, add role to the shared `fields` object
(after `tutor: config.tutor,`):

```javascript
      role: config.role,
```

(Both the multipart and JSON branches serialize `fields`, so one line covers
both.)

In `sandbox_ui/templates/embed.html`, bump the chat.js cache-buster:

```jinja
{% block chat_js_src %}{{ url_for('static', filename='js/chat.js', v='23') }}{% endblock %}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m sandbox_ui.routes.test_role_param`
Expected: all PASS

Regressions:
Run: `python -m sandbox_ui.routes.test_embed_no_course`
Run: `python -m sandbox_ui.routes.test_embed_practice`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add sandbox_ui/routes/_validation.py sandbox_ui/routes/embed.py sandbox_ui/routes/chat.py sandbox_ui/static/js/chat.js sandbox_ui/templates/embed.html sandbox_ui/routes/test_role_param.py
git commit -m "feat(sandbox_ui): add role query param (parity with main_ui)"
```

---

### Task 6: Documentation

**Files:**
- Modify: `tutor/README.md` (role concept + folder-per-role + how to add a role)
- Modify: `README.md` (note the `role` param on both web apps)

**Interfaces:** none (docs only).

- [ ] **Step 1: Update `tutor/README.md`**

Add a "Roles" subsection near the prompt-selection description. Content to add
(adjust surrounding prose to fit):

```markdown
### Roles

A *role* selects which prompt family the web apps (`main_ui`, `sandbox_ui`)
use, via a `role` URL query param (default `tutor`). Roles are declared in
`tutor/roles.py`:

- `role=tutor` → `tutor/prompts/`, default prompt `tutor_07` (the deployed
  default; both apps stay locked to their role's default prompt).
- `role=ta` → a future `ta/prompts/` folder — **not shipped**; requesting it
  404s until added.

**Adding a role** (e.g. `ta`):
1. Create `ta/prompts/ta_01.txt` (and any variants).
2. Register it in `tutor/roles.py`:
   `"ta": Role("ta", _REPO_ROOT / "ta" / "prompts", "ta_01")`.

Prompt names are unique per role (`tutor_*` vs `ta_*`); the web bridge resolves
a prompt's folder from its name, so no per-conversation role is stored.
```

- [ ] **Step 2: Update top-level `README.md`**

Find the passage describing `DEFAULT_TUTOR` / the single-prompt lock (search for
`DEFAULT_TUTOR` or `locked`) and add a sentence:

```markdown
Both web apps also accept a `role` query param (default `tutor`) that selects
the prompt family — `role=tutor` uses `tutor/prompts/` (`tutor_07`); other roles
(e.g. a future `ta`) 404 until registered in `tutor/roles.py`. Each role stays
locked to its default prompt.
```

- [ ] **Step 3: Commit**

```bash
git add tutor/README.md README.md
git commit -m "docs: document the role param and how to add roles"
```

---

## Self-Review

**Spec coverage:**
- Role registry (`tutor/roles.py`) → Task 1. ✅
- `load_system_prompt` `prompts_dir` → Task 2. ✅
- Bridge resolves folder via registry (no migration) → Task 3. ✅
- main_ui web layer (`_validation`, `embed`, `chat`, `chat.js`, cache bump) → Task 4. ✅
- sandbox_ui web layer (parity) → Task 5. ✅
- `role=ta`/`bogus` → 404; default → `tutor_07` → Tasks 4/5 tests. ✅
- Empty-course regression under a role → Tasks 4/5 tests + existing test_embed_no_course. ✅
- READMEs + docstrings → Task 6 (+ docstrings edited inline in Tasks 4/5). ✅
- Out of scope: sandbox context-switcher wiring, ta content, DB migration — not implemented. ✅

**Placeholder scan:** No TBD/TODO; every code + test block is concrete.

**Type consistency:** `validate_role(role) -> dict | None`, `role_default_prompt(role) -> str | None`, `get_role -> Role | None`, `prompts_dir_for_prompt -> Path | None`, `load_system_prompt(..., prompts_dir=None)`, `_render_embed(..., role=DEFAULT_ROLE)` used consistently across tasks. `tutor_config` key is `"role"` in both apps; sandbox keeps its `exerciseKind` key. main_ui `tutor_config` keeps `exercise_kind` + `labels`.
```
