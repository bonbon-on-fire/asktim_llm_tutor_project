# Design: `problem` focus param for the web UIs (main_ui + sandbox_ui)

Date: 2026-08-06
Status: Approved (design), pending implementation plan

## Problem

A course week's file (`practices/practice_N.txt` or `exercises/exercise_N.txt`)
contains **several sub-problems** — `Practice Problem 1:`, `Practice Problem 2:`
… in a practice file; `Graded Assignment 1:`, `Graded Assignment 2:` … in a
graded file. The embed widget loads the **entire file**, so the tutor already
sees every sub-problem, but it has no idea **which one the student is currently
working on**. Every conversation starts context-blind to the student's actual
position in the week.

We want an optional `problem=<n>` query param that marks one sub-problem as the
**focus**: the tutor is told the student is working on that specific problem,
while keeping access to the rest of the week's problems (already in context)
for reference.

## Scope

- **Both `main_ui` and `sandbox_ui`.** Full parity: same param, validation,
  persistence, and prompt wiring. `database_ui` gets the model column only (it's
  a read-only viewer of the same schema).
- **Granularity = sub-problem.** A "problem" is one `Practice Problem N:` /
  `Graded Assignment N:` header within the selected week's file.
- **Week scope = the same file only.** The focus problem's siblings are the
  other sub-problems already loaded from that file. The sibling graded/practice
  file for the same week is **not** pulled in. This is a focus-marking feature,
  not a context-expansion one.
- **Param shape = additive.** `problem=<n>` sits alongside the existing
  `exercise=`/`practice=` selection, which still chooses the week's file.
- **Persisted per conversation.** A new nullable `focus_problem` column on
  `conversations`, captured at creation and reused for later turns — parity with
  how `exercise_number` / `exercise_kind` / `tutor_prompt` defend an existing
  conversation against a frontend silently switching context mid-chat.
- **Out of scope:** wiring `problem` into sandbox_ui's context-switcher wizard
  UI; slicing the focus problem's text out of the file (the whole file still
  loads, the focus is named, not extracted); any change to RAG week-scoping.

## Current architecture (as-is)

- A week's file is selected by `course` + (`exercise` XOR `practice`) + the
  resolved number/kind (`resolve_embed_selection`, `_validation.py`). Both apps'
  `embed.py` render `tutor_config` (`course`, `exercise`, `tutor`, `role`,
  `exerciseKind`/`exercise_kind`); `chat.js` echoes it back; `chat.py` validates
  and persists a `Conversation`, then calls the tutor bridge.
- `ui_core.tutor_bridge.build_assignment_text(course, exercise, **ctx)` reads
  the whole `practice_N.txt` / `exercise_N.txt` via
  `practice_path`/`exercise_path` and folds it in under `"Exercise:\n<text>"`.
  `cache_key` keys the prompt cache on
  `(tutor, course, exercise, exercise_kind, context_mode, provider)`.
- `Conversation` is defined per app (`main_ui/db/models.py`,
  `sandbox_ui/db/models.py`, `database_ui/db/models.py`) with `course`,
  `exercise_number`, `exercise_kind`, `tutor_prompt`. main_ui uses **Alembic**
  (current head `d2e724232980`, add_exercise_kind); sandbox_ui skips Alembic and
  adds missing nullable columns on boot via `_reconcile_columns()` in
  `run_app.py`.
- For an EXISTING conversation, `chat.py` uses the **stored** column values for
  the LLM call, not the request's — the mid-conversation-switch defense.

## Design

### 1. Sub-problem parser (new, `utils/curriculum.py`)

Two functions beside the existing file loaders:

```python
import re

# A sub-problem header: "Practice Problem 2: Papper" / "Graded Assignment 1: ...".
# Prefix is chosen by kind so a practice file never matches a graded header.
_SUBPROBLEM_PREFIX = {"practice": "Practice Problem", "exercise": "Graded Assignment"}
_SUBPROBLEM_RE_TMPL = r"^{prefix}\s+(\d+)\s*:\s*(.*)$"


def list_subproblems(course, number, kind="exercise", curriculum_root=None):
    """Ordered [(n, title), ...] sub-problems in a week's file.

    Scans the resolved practice_N/exercise_N file for header lines matching the
    kind's prefix ("Practice Problem N:" or "Graded Assignment N:"). Returns []
    when the file is missing or has no such headers (e.g. a single-problem file).
    """
    path = (practice_path if kind == "practice" else exercise_path)(course, number, curriculum_root)
    if not path.is_file():
        return []
    prefix = _SUBPROBLEM_PREFIX["practice" if kind == "practice" else "exercise"]
    rx = re.compile(_SUBPROBLEM_RE_TMPL.format(prefix=re.escape(prefix)))
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        m = rx.match(line.strip())
        if m:
            out.append((int(m.group(1)), m.group(2).strip()))
    return out


def subproblem_label(course, number, kind, problem, curriculum_root=None):
    """"Practice Problem 2: Papper" for the focus number, or None if absent."""
    for n, title in list_subproblems(course, number, kind, curriculum_root):
        if n == int(problem):
            prefix = _SUBPROBLEM_PREFIX["practice" if kind == "practice" else "exercise"]
            return f"{prefix} {n}: {title}" if title else f"{prefix} {n}"
    return None
```

`problem` is matched against the **labeled header number** (`Practice Problem 2`
→ `problem=2`), which is sequential 1..N in every file inspected.

### 2. Validation (`_validation.py`, both apps)

```python
def validate_problem(course, number, kind, problem) -> dict | None:
    """None when problem is absent (no focus) or a valid sub-problem; else a failure dict.

    An empty/None problem is a no-op (focus is optional). Otherwise it must be a
    positive-integer string naming an existing sub-problem in the resolved file.
    """
    if not problem:
        return None
    if not (isinstance(problem, str) and problem.isdigit()):
        return _err("problem", problem, "must be a positive integer (e.g. 2)")
    if subproblem_label(course, number, kind, problem) is None:
        return _err("problem", problem, f"no sub-problem {problem} in {kind} {number} of {course}")
    return None
```

Validated **after** the file selection resolves (needs the final number+kind).

### 3. embed.py (both apps)

- `problem = request.args.get("problem")` (raw; may be None).
- After `resolve_embed_selection` yields `(number, kind)` and course validates,
  call `validate_problem(course, number, kind, problem)` → 404 on failure.
- Add `problem` to `tutor_config` (echoed by the frontend). Absent → omitted /
  empty, and the whole file loads with no focus (today's behavior).
- Empty-course path is unchanged: no course → no file → `problem` is ignored
  (nothing to validate against).

### 4. chat.js (both apps)

- Send `config.problem` in both the multipart and JSON payloads (beside
  `exercise`/`role`).
- Bump the `?v=` cache-buster on the `chat.js` include in each app's
  `templates/embed.html` (**and** the sandbox chat.js cache-version note).

### 5. Persistence (`Conversation` model + migration)

New column on `conversations`, **nullable** (NULL = no focus):

```python
# main_ui/db/models.py and database_ui/db/models.py
focus_problem: Mapped[int | None] = mapped_column(Integer, nullable=True)
# sandbox_ui/db/models.py — same; _reconcile_columns() adds it on boot.
focus_problem: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

**main_ui Alembic migration** (chains from head `d2e724232980`):

```python
def upgrade():
    op.add_column("conversations", sa.Column("focus_problem", sa.Integer(), nullable=True))

def downgrade():
    op.drop_column("conversations", "focus_problem")
```

sandbox_ui needs **no migration** — `_reconcile_columns()` already adds any
model-declared nullable column missing from the live table on boot.

**Services wrappers** (`<app>/services/conversation.py`): add a
`focus_problem: int | None = None` param, passed to the shared
`find_or_create_conversation` via `extra_fields={"focus_problem": ...}` (main_ui)
or the existing kwargs path (sandbox). Legacy/no-focus rows store NULL.

### 6. chat.py (both apps)

- Read `problem = src.get("problem")`; `validate_problem(course, number, kind,
  problem)` → 404 (reusing the resolved number/kind).
- New conversation: persist `focus_problem = int(problem) if problem else None`.
- Capture `stream_focus_problem = convo.focus_problem` alongside the other
  `stream_*` snapshots and thread it into `stream_kwargs` as
  `focus_problem=stream_focus_problem`. Existing conversation → uses the **stored**
  value (the mid-switch defense), matching `exercise`/`kind`/`tutor`.

### 7. tutor_bridge (`build_assignment_text` + `cache_key`)

- `build_assignment_text` reads `focus_problem = ctx.get("focus_problem")`. When
  set and `subproblem_label(course, exercise, kind, focus_problem)` resolves,
  prepend one directive **before** the existing `"Exercise:\n<file>"` block:

  ```
  Focus: the student is currently working on "Practice Problem 2: Papper".
  The full set of this week's problems is included below; help with the focus
  problem first, and treat the others as reference unless the student asks
  about them.
  ```

  When `focus_problem` is None or unresolvable, the assignment text is
  **byte-identical to today** (no focus line).
- Add `focus_problem` to `cache_key` so two foci over the same file get separate
  cached (model, system_prompt) entries.

### 8. URL behavior

```
/embed?course=X&practice=2            → whole file, no focus (unchanged)
/embed?course=X&practice=2&problem=2  → whole file, focus = "Practice Problem 2: ..."
/embed?course=X&exercise=2&problem=2  → whole file, focus = "Graded Assignment 2: ..."
/embed?course=X&practice=2&problem=99 → 404 (no such sub-problem)
/embed?course=X&practice=2&problem=ab → 404 (not a positive integer)
/embed?course=X                       → default exercise, no focus (unchanged)
```

## READMEs to update

- Top-level `README.md` — where it documents the embed params (`course`,
  `exercise`/`practice`, `role`), add the optional `problem=<n>` focus param and
  that it's persisted per conversation.
- Route docstrings in each app's `embed.py` / `chat.py`.

## Testing

Parser / validation (shared, `utils` + each app's `_validation`):
- `list_subproblems` finds the `Practice Problem N` headers in a practice file
  and `Graded Assignment N` headers in a graded file; missing/headerless → `[]`.
- `subproblem_label` returns the labeled title for a valid n, `None` otherwise.
- `validate_problem`: absent → None; non-integer → fail; out-of-range → fail;
  valid → None.

Per app (both `main_ui` and `sandbox_ui`):
- `/embed?...&problem=2` → 200 and `tutor_config` carries `problem`.
- `/embed?...&problem=99` and `problem=abc` → 404.
- `POST /api/chat` (new convo) with a valid `problem` persists
  `focus_problem = 2`; with no `problem` persists NULL; with a bad `problem` →
  404. Existing convo ignores a differing request `problem` (stored value wins).
- Regression: no `problem` → assignment text and `tutor_config` unchanged.

Bridge (`ui_core`):
- `build_assignment_text` with `focus_problem` set prepends the focus line and
  still contains the full file; without it, output is unchanged.
- `cache_key` differs for two different `focus_problem` values.

## Non-goals

- No sibling-file loading (graded + practice together) — same-file scope only.
- No extraction/highlighting of the focus problem's text; the whole file loads
  and the focus is named.
- No `problem` wiring into the sandbox context-switcher wizard UI.
- No change to RAG week-scoping (`_week_for_exercise` still keys off the week
  number, not the focus sub-problem).
