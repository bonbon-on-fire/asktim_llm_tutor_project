# Design: `role` param for the main UI

Date: 2026-08-06
Status: Approved (design), pending implementation plan

## Problem

The main UI is hard-locked to a single tutor prompt: both `embed.py` and
`chat.py` force `tutor = DEFAULT_TUTOR` (`"tutor_07"`) and ignore any
client-supplied value. There is no way to select a *different kind* of
assistant persona — e.g. a teaching assistant ("TA") with its own prompt
family — from the URL.

We want a `role` query param that selects which prompt family to use:

- `role=tutor` (the default) → `tutor/prompts/tutor_07.txt` (today's behavior).
- `role=ta` → a future `ta/prompts/ta_*.txt` folder.

Right now only the `tutor` role is functional. The `ta` role is scaffolded for
later: requesting it 404s until someone creates `ta/prompts/` and registers the
role.

## Scope

- **main_ui only.** `sandbox_ui` is intentionally NOT given a `role` param.
- The shared `tutor.load_system_prompt` change is backward-compatible, so
  `sandbox_ui` and the `tutor/` CLI are unaffected.
- No database migration.

## Current architecture (as-is)

- Prompts live in `tutor/prompts/<name>.txt`.
  `PROMPTS_DIR = tutor/prompts/` (`tutor/run_tutor.py:37`).
- `load_system_prompt(prompt_name, assignment_override=None)` reads
  `PROMPTS_DIR / f"{prompt_name}.txt"` (`tutor/run_tutor.py:71`).
- `DEFAULT_TUTOR = "tutor_07"`; `validate_tutor()` checks the file exists
  (`main_ui/routes/_validation.py`).
- Flow: `embed.py` sets `tutor = DEFAULT_TUTOR` → rendered into `tutor_config`;
  `chat.js` echoes `config.tutor` back → `chat.py` ignores it and re-forces
  `DEFAULT_TUTOR` → stores `conversation.tutor_prompt` →
  `ui_core.tutor_bridge.build_system_prompt(tutor=...)` calls
  `load_system_prompt(tutor)`.
- For an EXISTING conversation, `chat.py` uses the stored
  `convo.tutor_prompt` for the LLM call (defends against a frontend silently
  switching context mid-conversation).

## Design

### 1. Role registry (new: `tutor/roles.py`)

A single source of truth mapping a role name to its prompt folder and default
prompt:

```python
from dataclasses import dataclass
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]

@dataclass(frozen=True)
class Role:
    name: str
    prompts_dir: Path
    default_prompt: str

DEFAULT_ROLE = "tutor"

ROLES: dict[str, Role] = {
    "tutor": Role("tutor", _REPO_ROOT / "tutor" / "prompts", "tutor_07"),
    # Add when ta/prompts/ exists and has a default prompt file:
    # "ta": Role("ta", _REPO_ROOT / "ta" / "prompts", "ta_01"),
}

def get_role(name: str | None) -> Role | None:
    """Return the Role for *name*, or None if unknown/unregistered."""
    return ROLES.get(name) if name else None

def prompts_dir_for_prompt(prompt_name: str) -> Path | None:
    """Reverse-lookup: the registered prompts_dir whose folder owns
    <prompt_name>.txt. Prompt names are unique per role (tutor_* vs ta_*),
    so at most one matches. Returns None if no registered role owns it."""
    for role in ROLES.values():
        if (role.prompts_dir / f"{prompt_name}.txt").is_file():
            return role.prompts_dir
    return None
```

Adding the `ta` role later is a one-line registry change plus creating
`ta/prompts/`. Until then, `role=ta` is simply an unknown role.

### 2. Prompt loading (`tutor/run_tutor.py`)

`load_system_prompt` gains an optional `prompts_dir`:

```python
def load_system_prompt(prompt_name="tutor_01", assignment_override=None,
                       prompts_dir=None):
    base_dir = prompts_dir or PROMPTS_DIR   # default = tutor/prompts (unchanged)
    path = base_dir / f"{prompt_name}.txt"
    ...
```

Every existing caller keeps working (default `prompts_dir=None` → `PROMPTS_DIR`).

### 3. tutor_bridge threads the folder through

`ui_core.tutor_bridge.build_system_prompt` resolves the folder for the prompt
via `roles.prompts_dir_for_prompt(tutor)` and passes it to
`load_system_prompt(tutor, ..., prompts_dir=<resolved>)`. Falls back to the
default tutor folder when the reverse-lookup returns None (keeps existing
behavior for any prompt name not owned by a registered role). This is what lets
an existing conversation resolve its folder from the stored `tutor_prompt`
alone — no persisted `role`, no migration.

### 4. Web layer (`main_ui`)

**`_validation.py`:**
- Import `DEFAULT_ROLE`, `get_role` from `tutor.roles`.
- `validate_role(role) -> dict | None` — `None` if `role` is a registered role,
  else a failure dict (`{param: "role", value, reason}`).
- `role_default_prompt(role) -> str` — the resolved default prompt name for a
  valid role (e.g. `"tutor_07"`).
- Keep `DEFAULT_TUTOR` for tutor's default (it equals
  `ROLES["tutor"].default_prompt`).

**`embed.py`:**
- `role = request.args.get("role") or DEFAULT_ROLE`.
- `validate_role(role)` → 404 on failure (`_bad_param`).
- Resolve the role's default prompt; pass it as `tutor` and also add `role` to
  `tutor_config` so the frontend echoes it back.
- Empty-course behavior is unchanged: no course still renders an empty context
  (and 404s on send). Role is resolved regardless.

**`chat.py`:**
- `role = src.get("role") or DEFAULT_ROLE`; `validate_role(role)` → 404.
- For a **new** conversation, use `role_default_prompt(role)` instead of the
  hardcoded `DEFAULT_TUTOR`. For an **existing** conversation, keep using the
  stored `convo.tutor_prompt` (unchanged guarantee).

**`chat.js`:**
- Send `config.role` in both the multipart and JSON payloads.
- Bump the `?v=` cache-buster on the `chat.js` include in
  `main_ui/templates/embed.html`.

### 5. URL behavior

```
/embed?course=X                 → role=tutor → tutor_07   (unchanged default)
/embed?course=X&role=tutor      → tutor_07
/embed?course=X&role=ta         → 404 (role not available yet)
/embed?course=X&role=bogus      → 404 (no such role)
/  (bare host)                  → role=tutor, empty course (renders; send 404s)
```

### 6. TA folder

Not created in this change (scaffold-only). Adding it later:
1. Create `ta/prompts/ta_01.txt` (and any variants).
2. Uncomment/add the `"ta"` entry in `ROLES`.
No code changes beyond that.

## READMEs to update

- `tutor/README.md` — introduce the role concept, the folder-per-role layout
  (`tutor/prompts/`, future `ta/prompts/`), and "how to add a role".
- Top-level `README.md` — where it describes prompt selection / the
  `DEFAULT_TUTOR` lock, note the new `role` param (main_ui only) and that each
  role is locked to its default prompt.
- Route docstrings in `embed.py` / `chat.py`.

## Testing

- `role` defaults to `tutor` → resolves `tutor_07`.
- `/embed` with no role, `role=tutor` → 200.
- `/embed?role=ta` and `?role=bogus` → 404.
- `POST /api/chat` with `role=bogus` → 404; with `role=tutor` (new
  conversation) stores `tutor_prompt = "tutor_07"`.
- `load_system_prompt` works with no `prompts_dir` (default folder) and with an
  explicit `prompts_dir`.
- `roles.prompts_dir_for_prompt("tutor_07")` returns the tutor folder;
  unknown name returns None.
- Regression: empty-course behavior still holds under a role.

## Non-goals

- No `ta` prompt content shipped.
- No `role` param for `sandbox_ui` (and no change to sandbox's existing params).
- No DB migration / persisted `role` column.
- Per-role prompt *variant* selection from the client stays locked (each role
  uses its single default prompt), matching today's production lock.
```
