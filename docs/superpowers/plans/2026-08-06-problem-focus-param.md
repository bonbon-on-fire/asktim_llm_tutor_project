# `problem` Focus Param Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional `problem=<n>` URL query param to both web apps that marks one sub-problem in the already-loaded week file as the student's focus, persisted per conversation and surfaced to the tutor as a directive.

**Architecture:** A shared curriculum parser resolves `Practice Problem N:` / `Graded Assignment N:` headers inside the selected week file. Each app validates `problem` after resolving its file selection, persists it as a nullable `focus_problem` column on `conversations`, and threads the stored value through `stream_kwargs` → the tutor bridge, which prepends one focus directive before the (unchanged) whole-file assignment text and keys the prompt cache on it. Full main_ui/sandbox_ui parity; database_ui gets the read-only column.

**Tech Stack:** Python 3, Flask, SQLAlchemy 2.x, Alembic (main_ui only), vanilla JS. Tests are self-contained `python -m <module>` scripts with a `main() -> int` and a `_check`/print harness — **no pytest** (repo convention).

## Global Constraints

- **No `Co-Authored-By: Claude` trailer** in any commit.
- **Conventional commits always**: `type(scope): subject`.
- **Bump the `?v=` cache-buster** on the `chat.js` include in an app's `templates/embed.html` whenever that app's `chat.js` is edited (main_ui currently `v='7'`, sandbox_ui currently `v='23'`).
- **Do NOT push** without explicit user authorization. **Do NOT force-push** without explicit consent.
- **`problem` is optional and additive.** When absent/empty, every code path must be **byte-identical to today's behavior** (no focus line, `focus_problem` persisted as NULL, `tutor_config` unchanged, cache key equivalent).
- **`problem` matches the labeled header number** (`Practice Problem 2` → `problem=2`), validated against the resolved `(number, kind)` file, not a file offset.
- **Existing conversations use STORED column values** for the LLM call (mid-conversation-switch defense) — `focus_problem` follows the same rule as `exercise_number`/`exercise_kind`/`tutor_prompt`.
- **Focus directive text (verbatim), prepended before the `Exercise:\n<file>` block:**
  ```
  Focus: the student is currently working on "<label>".
  The full set of this week's problems is included below; help with the focus problem first, and treat the others as reference unless the student asks about them.
  ```
  where `<label>` is `subproblem_label(...)` (e.g. `Practice Problem 2: SteelCo`).

---

### Task 1: Sub-problem parser in `utils/curriculum.py`

**Files:**
- Modify: `utils/curriculum.py` (add after the `read_solution` function, ~line 268+; `import re` is already present at line 13)
- Test: `utils/test_subproblems.py` (Create)

**Interfaces:**
- Consumes: existing `exercise_path(course, number, curriculum_root=None)`, `practice_path(course, number, curriculum_root=None)` from the same module.
- Produces:
  - `list_subproblems(course, number, kind="exercise", curriculum_root=None) -> list[tuple[int, str]]` — ordered `(n, title)` sub-problems; `[]` when the file is missing or headerless.
  - `subproblem_label(course, number, kind, problem, curriculum_root=None) -> str | None` — `"Practice Problem 2: SteelCo"` for a matching `n`, else `None`.
  - Module constant `_SUBPROBLEM_PREFIX = {"practice": "Practice Problem", "exercise": "Graded Assignment"}`.

- [ ] **Step 1: Write the failing test**

Create `utils/test_subproblems.py`. `supply_chain_design` is a real active course: its `practices/practice_1.txt` has `Practice Problem 1: Network Model Basics` … and `exercises/exercise_1.txt` has `Graded Assignment 1: Locky Locke Inc.` …

```python
"""Parser checks for sub-problem headers in a week file.

Run:
    python -m utils.test_subproblems
"""
from __future__ import annotations

from utils.curriculum import list_subproblems, subproblem_label

COURSE = "supply_chain_design"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True

    # Practice file: "Practice Problem N:" headers.
    pp = list_subproblems(COURSE, "1", "practice")
    ok &= _check("practice headers found", len(pp) >= 2, len(pp))
    ok &= _check("practice first is (1, title)", pp and pp[0][0] == 1 and bool(pp[0][1]), pp[:1])

    # Graded file: "Graded Assignment N:" headers.
    ga = list_subproblems(COURSE, "1", "exercise")
    ok &= _check("graded headers found", len(ga) >= 2, len(ga))
    ok &= _check("graded first is (1, title)", ga and ga[0][0] == 1, ga[:1])

    # A practice file must NOT match the graded prefix (kind isolation).
    ok &= _check("practice kind ignores graded headers",
                 all(True for _ in pp) and list_subproblems(COURSE, "1", "practice") == pp)

    # subproblem_label
    lbl = subproblem_label(COURSE, "1", "practice", "2")
    ok &= _check("label for problem 2", lbl is not None and lbl.startswith("Practice Problem 2:"), lbl)
    ok &= _check("label accepts int problem", subproblem_label(COURSE, "1", "practice", 2) == lbl)
    ok &= _check("label None for missing n", subproblem_label(COURSE, "1", "practice", "999") is None)

    # Missing file -> [] and None (no crash).
    ok &= _check("missing file -> []", list_subproblems(COURSE, "99", "practice") == [])
    ok &= _check("missing file -> label None", subproblem_label(COURSE, "99", "practice", "1") is None)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m utils.test_subproblems`
Expected: FAIL / ImportError — `list_subproblems` / `subproblem_label` not defined.

- [ ] **Step 3: Write minimal implementation**

Add to `utils/curriculum.py` (after `read_solution`):

```python
# A sub-problem header line: "Practice Problem 2: SteelCo" / "Graded Assignment 1: ...".
# The prefix is chosen by kind so a practice file never matches a graded header.
_SUBPROBLEM_PREFIX = {"practice": "Practice Problem", "exercise": "Graded Assignment"}
_SUBPROBLEM_RE_TMPL = r"^{prefix}\s+(\d+)\s*:\s*(.*)$"


def list_subproblems(course, number, kind="exercise", curriculum_root=None):
    """Ordered ``[(n, title), ...]`` sub-problems in a week's file.

    Scans the resolved practice_N/exercise_N file for header lines matching the
    kind's prefix ("Practice Problem N:" or "Graded Assignment N:"). Returns
    ``[]`` when the file is missing or has no such headers (e.g. a single-problem
    file with no header).
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
    """``"Practice Problem 2: SteelCo"`` for the focus number, or ``None`` if absent.

    ``problem`` may be an int or a digit string; it is matched against the
    labeled header number. Title-less headers degrade to just the prefix + n.
    """
    for n, title in list_subproblems(course, number, kind, curriculum_root):
        if n == int(problem):
            prefix = _SUBPROBLEM_PREFIX["practice" if kind == "practice" else "exercise"]
            return f"{prefix} {n}: {title}" if title else f"{prefix} {n}"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m utils.test_subproblems`
Expected: PASS (all lines).

- [ ] **Step 5: Commit**

```bash
git add utils/curriculum.py utils/test_subproblems.py
git commit -m "feat(curriculum): parse Practice Problem / Graded Assignment sub-problem headers"
```

---

### Task 2: Focus directive + cache key in `ui_core/tutor_bridge.py`

**Files:**
- Modify: `ui_core/tutor_bridge.py` — import block (lines 58-67), `cache_key` (lines 273-286), `build_assignment_text` (lines 288-337)
- Test: `ui_core/test_tutor_bridge_focus.py` (Create)

**Interfaces:**
- Consumes: `subproblem_label` from Task 1; `ctx.get("focus_problem")` (threaded by the routes in Tasks 5/6 via `stream_kwargs`). `ctx` already carries `exercise_kind` today.
- Produces: focus directive prepended before the `Exercise:` block when `focus_problem` resolves; `focus_problem` added to the cache-key tuple. `TutorBridge` is the base class; both apps' bridges inherit these unless overridden (they are not).

- [ ] **Step 1: Write the failing test**

Create `ui_core/test_tutor_bridge_focus.py`:

```python
"""Focus-directive + cache-key checks for the tutor bridge.

Run:
    python -m ui_core.test_tutor_bridge_focus
"""
from __future__ import annotations

from ui_core.tutor_bridge import TutorBridge

COURSE = "supply_chain_design"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    b = TutorBridge()

    base = b.build_assignment_text(COURSE, "1", exercise_kind="practice", context_mode="full_context")
    focused = b.build_assignment_text(
        COURSE, "1", exercise_kind="practice", context_mode="full_context", focus_problem=2
    )

    ok &= _check("no focus_problem -> unchanged text",
                 b.build_assignment_text(COURSE, "1", exercise_kind="practice",
                                         context_mode="full_context", focus_problem=None) == base)
    ok &= _check("focus text prepends directive", "Focus: the student is currently working on" in focused)
    ok &= _check("focus text names the sub-problem", "Practice Problem 2:" in focused)
    ok &= _check("focus text still contains full file", "Exercise:\n" in focused and base.split("Exercise:\n", 1)[1] in focused)
    ok &= _check("unresolvable focus -> unchanged text",
                 b.build_assignment_text(COURSE, "1", exercise_kind="practice",
                                         context_mode="full_context", focus_problem=999) == base)

    k_none = b.cache_key("tutor_07", COURSE, "1", exercise_kind="practice")
    k2 = b.cache_key("tutor_07", COURSE, "1", exercise_kind="practice", focus_problem=2)
    k3 = b.cache_key("tutor_07", COURSE, "1", exercise_kind="practice", focus_problem=3)
    ok &= _check("cache key differs by focus", k2 != k3 and k2 != k_none, (k_none, k2, k3))

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m ui_core.test_tutor_bridge_focus`
Expected: FAIL — no focus line in `focused`, and `k2 == k3` (cache_key ignores focus).

- [ ] **Step 3: Write minimal implementation**

In the import block (lines 58-67), add `subproblem_label` (keep alphabetical grouping):

```python
from utils.curriculum import (
    SOLUTION_CONTEXT_LABEL,
    append_course_tutor_rules,
    exercise_path,
    load_about_asktim,
    practice_path,
    read_exercise,
    read_pinned_context,
    read_solution,
    subproblem_label,
)
```

In `cache_key` (lines 279-286), append `focus_problem` to the returned tuple:

```python
        return (
            tutor,
            course,
            exercise,
            ctx.get("exercise_kind", "exercise"),
            ctx.get("context_mode", "full_context"),
            _resolve_provider(ctx.get("provider")),
            ctx.get("focus_problem"),
        )
```

In `build_assignment_text`, replace the single line `parts.append("Exercise:\n" + exercise_text)` (line 329) with the focus directive followed by the Exercise block:

```python
        # Optional focus directive: names the one sub-problem the student is
        # working on. The whole file still loads below; the directive only marks
        # the focus. Absent/unresolvable -> byte-identical to no-focus output.
        focus_problem = ctx.get("focus_problem")
        if focus_problem:
            label = subproblem_label(course, exercise, kind, focus_problem)
            if label:
                parts.append(
                    f'Focus: the student is currently working on "{label}".\n'
                    "The full set of this week's problems is included below; help "
                    "with the focus problem first, and treat the others as reference "
                    "unless the student asks about them."
                )

        parts.append("Exercise:\n" + exercise_text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m ui_core.test_tutor_bridge_focus`
Expected: PASS.

- [ ] **Step 5: Run the existing bridge regression tests**

Run: `python -m ui_core.test_tutor_bridge` and `python -m ui_core.test_tutor_bridge_practice`
Expected: PASS (no-focus output unchanged).

- [ ] **Step 6: Commit**

```bash
git add ui_core/tutor_bridge.py ui_core/test_tutor_bridge_focus.py
git commit -m "feat(ui_core): prepend focus directive and key cache on focus_problem"
```

---

### Task 3: `focus_problem` column across models + main_ui migration

**Files:**
- Modify: `main_ui/db/models.py` (Conversation, after `exercise_kind`, ~line 46)
- Modify: `sandbox_ui/db/models.py` (Conversation — same nullable column; `_reconcile_columns()` in `run_app.py` adds it on boot, no migration)
- Modify: `database_ui/db/models.py` (Conversation — read-only mapping, after `exercise_kind`, ~line 53)
- Create: `main_ui/db/migrations/versions/b3d9f1a4c027_add_focus_problem.py`
- Test: `main_ui/db/test_focus_problem_migration.py` (Create)

**Interfaces:**
- Consumes: nothing from prior tasks.
- Produces: `Conversation.focus_problem: Mapped[int | None]` on all three apps' models; migration `b3d9f1a4c027` chaining from head `d2e724232980`.

**Note — `Integer` imports:** Both `main_ui/db/models.py` (line 14: `from sqlalchemy import DateTime, Index, Text, Uuid`) and `sandbox_ui/db/models.py` (line 15: `from sqlalchemy import Boolean, DateTime, Index, Text, Uuid`) **lack `Integer`** — add it to each import in this task. `database_ui/db/models.py` already imports `Integer`.

- [ ] **Step 1: Write the failing test**

Create `main_ui/db/test_focus_problem_migration.py`. It builds a fresh in-memory schema from the models and asserts the column exists and defaults to NULL.

```python
"""Schema check: conversations.focus_problem exists and defaults to NULL.

Run:
    python -m main_ui.db.test_focus_problem_migration
"""
from __future__ import annotations

import uuid

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from main_ui.db.models import Base, Conversation


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    ok &= _check("column mapped", hasattr(Conversation, "focus_problem"))

    with Session(engine) as s:
        c = Conversation(
            session_id="sess", course="supply_chain_design",
            exercise_number="1", tutor_prompt="tutor_07",
        )
        s.add(c)
        s.commit()
        ok &= _check("defaults to NULL", c.focus_problem is None, c.focus_problem)

        c2 = Conversation(
            session_id="sess", course="supply_chain_design",
            exercise_number="1", tutor_prompt="tutor_07", focus_problem=2,
        )
        s.add(c2)
        s.commit()
        ok &= _check("stores an int", c2.focus_problem == 2, c2.focus_problem)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m main_ui.db.test_focus_problem_migration`
Expected: FAIL — `Conversation` has no `focus_problem` attribute.

- [ ] **Step 3: Add the column to all three models**

`main_ui/db/models.py` — add `Integer` to the sqlalchemy import and the column after `exercise_kind` (line 46):

```python
from sqlalchemy import DateTime, Index, Integer, Text, Uuid
```

```python
    # Optional focus: the one sub-problem (Practice Problem N / Graded Assignment
    # N header) in exercise_number's file the student is working on. NULL = no
    # focus (whole file, today's behavior). Set at conversation creation and
    # replayed on later turns (mid-switch defense, like exercise_kind).
    focus_problem: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

`sandbox_ui/db/models.py` — add `Integer` to the import and the column on its `Conversation`, placed after `exercise_kind`:

```python
from sqlalchemy import Boolean, DateTime, Index, Integer, Text, Uuid
```

```python
    # Optional focus sub-problem in exercise_number's file (see main_ui). NULL =
    # no focus. _reconcile_columns() adds this nullable column on boot; no Alembic.
    focus_problem: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

`database_ui/db/models.py` — read-only mapping after `exercise_kind` (line 53); `Integer` is already imported:

```python
    # Optional focus sub-problem in exercise_number's file (see main_ui/sandbox_ui).
    # Present in both live schemas; NULL for pre-feature / no-focus rows. Read-only.
    focus_problem: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 4: Write the main_ui Alembic migration**

Create `main_ui/db/migrations/versions/b3d9f1a4c027_add_focus_problem.py`:

```python
"""add focus_problem

Revision ID: b3d9f1a4c027
Revises: d2e724232980
Create Date: 2026-08-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3d9f1a4c027'
down_revision: Union[str, Sequence[str], None] = 'd2e724232980'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("focus_problem", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "focus_problem")
```

- [ ] **Step 5: Run the schema test + confirm the migration is the single head**

Run: `python -m main_ui.db.test_focus_problem_migration`
Expected: PASS.

Run: `python -m alembic -c main_ui/db/migrations/alembic.ini heads`
Expected: a single head `b3d9f1a4c027`. If the command errors on config location, instead verify by inspection that exactly one migration file now has `down_revision = 'd2e724232980'` (the new one) and that `b3d9f1a4c027` is not referenced as any other migration's `down_revision`.

- [ ] **Step 6: Commit**

```bash
git add main_ui/db/models.py sandbox_ui/db/models.py database_ui/db/models.py main_ui/db/migrations/versions/b3d9f1a4c027_add_focus_problem.py main_ui/db/test_focus_problem_migration.py
git commit -m "feat(db): add nullable focus_problem column and main_ui migration"
```

---

### Task 4: Persist `focus_problem` through the services wrappers

**Files:**
- Modify: `main_ui/services/conversation.py` — `find_or_create_conversation` (lines 31-58)
- Modify: `sandbox_ui/services/conversation.py` — `find_or_create_conversation` (lines 31-66)
- Test: `main_ui/services/test_focus_problem_persist.py` (Create)

**Interfaces:**
- Consumes: the shared `ui_core.services.conversation.find_or_create_conversation(..., extra_fields=...)` (unchanged; `focus_problem` rides in `extra_fields`).
- Produces: both wrappers accept `focus_problem: int | None = None` and pass it via `extra_fields`. New conversations store the value; continuations return the existing row untouched (stored value wins).

- [ ] **Step 1: Write the failing test**

Create `main_ui/services/test_focus_problem_persist.py`:

```python
"""find_or_create_conversation persists focus_problem on new rows only.

Run:
    python -m main_ui.services.test_focus_problem_persist
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from main_ui.db.models import Base
from main_ui.services.conversation import find_or_create_conversation


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)

    with Session(engine) as db:
        convo = find_or_create_conversation(
            db, session_id="sess", conversation_id=None,
            course="supply_chain_design", exercise_number="1",
            tutor_prompt="tutor_07", exercise_kind="practice", focus_problem=2,
        )
        db.commit()
        ok &= _check("new convo stores focus", convo.focus_problem == 2, convo.focus_problem)

        # Continuation: a differing request focus must NOT overwrite the stored value.
        again = find_or_create_conversation(
            db, session_id="sess", conversation_id=convo.id,
            course="supply_chain_design", exercise_number="1",
            tutor_prompt="tutor_07", exercise_kind="practice", focus_problem=7,
        )
        ok &= _check("continuation keeps stored focus", again.focus_problem == 2, again.focus_problem)

        # No focus -> NULL.
        nofocus = find_or_create_conversation(
            db, session_id="sess2", conversation_id=None,
            course="supply_chain_design", exercise_number="1", tutor_prompt="tutor_07",
        )
        db.commit()
        ok &= _check("absent focus -> NULL", nofocus.focus_problem is None, nofocus.focus_problem)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m main_ui.services.test_focus_problem_persist`
Expected: FAIL — `find_or_create_conversation` got an unexpected keyword `focus_problem`.

- [ ] **Step 3: Thread `focus_problem` through both wrappers**

`main_ui/services/conversation.py` — add the param and pass it via `extra_fields`:

```python
def find_or_create_conversation(
    db: Session,
    *,
    session_id: str,
    conversation_id: UUID | None,
    course: str,
    exercise_number: str,
    tutor_prompt: str,
    exercise_kind: str = "exercise",
    focus_problem: int | None = None,
    username: str | None = None,
) -> Conversation:
    """Resolve to an existing conversation or insert a new one.

    Raises:
        WrongSessionError: if `conversation_id` was provided but either
            doesn't exist or belongs to a different session.
    """
    return _shared.find_or_create_conversation(
        db,
        models=_MODELS,
        session_id=session_id,
        conversation_id=conversation_id,
        course=course,
        exercise_number=exercise_number,
        tutor_prompt=tutor_prompt,
        username=username,
        extra_fields={"exercise_kind": exercise_kind, "focus_problem": focus_problem},
    )
```

`sandbox_ui/services/conversation.py` — add the param and the `extra_fields` key:

```python
def find_or_create_conversation(
    db: Session,
    *,
    session_id: str,
    conversation_id: UUID | None,
    course: str,
    exercise_number: str,
    exercise_kind: str = "exercise",
    tutor_prompt: str,
    focus_problem: int | None = None,
    username: str | None = None,
    lectures_enabled: bool = True,
    context_mode: str | None = None,
    provider: str | None = None,
) -> Conversation:
    """Resolve to an existing conversation or insert a new one.

    Raises:
        WrongSessionError: if `conversation_id` was provided but either
            doesn't exist or belongs to a different session.
    """
    return _shared.find_or_create_conversation(
        db,
        models=_MODELS,
        session_id=session_id,
        conversation_id=conversation_id,
        course=course,
        exercise_number=exercise_number,
        tutor_prompt=tutor_prompt,
        username=username,
        extra_fields={
            "exercise_kind": exercise_kind,
            "focus_problem": focus_problem,
            "lectures_enabled": lectures_enabled,
            "context_mode": context_mode,
            "provider": provider,
        },
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m main_ui.services.test_focus_problem_persist`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add main_ui/services/conversation.py sandbox_ui/services/conversation.py main_ui/services/test_focus_problem_persist.py
git commit -m "feat(services): persist focus_problem on new conversations (both apps)"
```

---

### Task 5: main_ui web layer — validation, embed, chat, chat.js

**Files:**
- Modify: `main_ui/routes/_validation.py` (import `subproblem_label`; add `validate_problem`)
- Modify: `main_ui/routes/embed.py` (`_render_embed`, `embed()`)
- Modify: `main_ui/routes/chat.py` (`chat()` — validate, persist, snapshot, thread into `stream_kwargs`)
- Modify: `main_ui/static/js/chat.js` (send `config.problem` in both payloads)
- Modify: `main_ui/templates/embed.html` (bump `chat.js` `v='7'` → `v='8'`)
- Test: `main_ui/routes/test_problem_focus.py` (Create)

**Interfaces:**
- Consumes: `subproblem_label` (Task 1), `find_or_create_conversation(..., focus_problem=)` (Task 4), the bridge's `focus_problem` ctx handling (Task 2).
- Produces: `validate_problem(course, number, kind, problem) -> dict | None`; `problem` in `tutor_config`; `focus_problem` persisted and threaded into `stream_kwargs`.

- [ ] **Step 1: Write the failing test**

Create `main_ui/routes/test_problem_focus.py`. Uses `supply_chain_design` (a real active course with sub-problems); probes `list_subproblems` to pick a valid number, else SKIPs that leg — mirroring `test_embed_practice`.

```python
"""Flask test-client checks for the problem-focus param in main_ui.

Run:
    python -m main_ui.routes.test_problem_focus
"""
from __future__ import annotations

from main_ui.run_app import app
from utils.curriculum import list_subproblems

COURSE = "supply_chain_design"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()

    subs = list_subproblems(COURSE, "1", "practice")
    if not subs:
        print("SKIP - no sub-problems for", COURSE, "practice 1")
        return 0
    n = subs[-1][0]  # a valid, in-range problem number

    r = client.get(f"/embed?course={COURSE}&practice=1&problem={n}")
    ok &= _check("valid problem renders", r.status_code == 200, r.status_code)
    ok &= _check("problem echoed in config",
                 (f'"problem": {n}' .encode() in r.data) or (f'"problem": "{n}"'.encode() in r.data),
                 r.data[:0])

    ok &= _check("out-of-range problem -> 404",
                 client.get(f"/embed?course={COURSE}&practice=1&problem=999").status_code == 404)
    ok &= _check("non-integer problem -> 404",
                 client.get(f"/embed?course={COURSE}&practice=1&problem=abc").status_code == 404)

    # No problem -> unchanged (200, no focus).
    ok &= _check("no problem still renders",
                 client.get(f"/embed?course={COURSE}&practice=1").status_code == 200)

    # POST /api/chat: a bad problem 404s before streaming.
    bad = client.post("/api/chat", json={
        "text": "hi", "course": COURSE, "exercise": "1",
        "exercise_kind": "practice", "problem": "999",
    })
    ok &= _check("chat bad problem -> 404", bad.status_code == 404, bad.status_code)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m main_ui.routes.test_problem_focus`
Expected: FAIL — `problem` not in config; bad-problem `/embed` and `/api/chat` return 200 instead of 404.

- [ ] **Step 3: Add `validate_problem` to `_validation.py`**

Add `subproblem_label` to the `utils.curriculum` imports at the top of `main_ui/routes/_validation.py`, then add:

```python
def validate_problem(course, number, kind, problem) -> dict | None:
    """None when problem is absent (no focus) or valid; else a failure dict.

    Empty/None problem is a no-op (focus is optional). Otherwise it must be a
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

- [ ] **Step 4: Wire `embed.py`**

Import `validate_problem` in the `_validation` import block. Add `problem` to `_render_embed` and validate it in `embed()`:

```python
def _render_embed(*, course: str, exercise: str, tutor: str, exercise_kind: str = "exercise", role: str = DEFAULT_ROLE, problem: str | None = None):
    """Render ``embed.html`` for the given course/exercise|practice/tutor/role/problem context."""
    tutor_config = {
        "course": course,
        "exercise": exercise,
        "tutor": tutor,
        "role": role,
        "exercise_kind": exercise_kind,
        "labels": load_ui_labels(course),
    }
    if problem:
        # Focus sub-problem (optional). Omitted when absent so no-focus config
        # stays byte-identical to today. Stored as an int for the frontend echo.
        tutor_config["problem"] = int(problem)
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

In `embed()`, after `resolve_embed_selection` and before the `validate_tutor` call, read + validate `problem`, then pass it to `_render_embed`:

```python
    number, kind, err = resolve_embed_selection(
        course, request.args.get("exercise"), request.args.get("practice"), DEFAULT_EXERCISE
    )
    if err:
        return _bad_param(err)

    problem = request.args.get("problem")
    err = validate_problem(course, number, kind, problem)
    if err:
        return _bad_param(err)

    err = validate_tutor(tutor)
    if err:
        return _bad_param(err)

    return _render_embed(course=course, exercise=number, tutor=tutor, exercise_kind=kind, role=role, problem=problem)
```

(The empty-course early returns and `index()` stay unchanged — no course means no file to validate a focus against.)

- [ ] **Step 5: Wire `chat.py`**

Import `validate_problem` in the `_validation` import block. After the existing `validate_selection` check (line 192-194), read + validate `problem`:

```python
    err = validate_selection(course, exercise, exercise_kind)
    if err:
        return _bad_param(err)
    problem = src.get("problem")
    err = validate_problem(course, exercise, exercise_kind, problem)
    if err:
        return _bad_param(err)
```

Pass `focus_problem` into `find_or_create_conversation` (new convos persist it; continuations ignore it — stored value wins):

```python
        convo = find_or_create_conversation(
            db,
            session_id=g.session_id,
            conversation_id=convo_id,
            course=course,
            exercise_number=exercise,
            exercise_kind=exercise_kind,
            focus_problem=int(problem) if problem else None,
            tutor_prompt=tutor,
            username=username,
        )
```

Snapshot the stored value alongside the other `stream_*` snapshots (after line 319):

```python
    stream_exercise_kind = convo.exercise_kind or "exercise"
    stream_focus_problem = convo.focus_problem
```

Add it to `stream_kwargs`:

```python
    stream_kwargs = dict(
        course=stream_course,
        exercise=stream_exercise,
        exercise_kind=stream_exercise_kind,
        focus_problem=stream_focus_problem,
        tutor=stream_tutor,
        history=history,
        new_student_message=student_text + files_service.files_to_text(attachments),
        images=images_to_tuples(images),
        history_mode=stream_history_mode,
        cached_history=cached_history,
    )
```

- [ ] **Step 6: Send `problem` from `chat.js`**

In `main_ui/static/js/chat.js`, add `problem` to both the multipart form (after line 1028) and the JSON payload (after line 1045), guarded so an absent focus sends nothing:

Multipart branch:
```javascript
      form.append("exercise_kind", config.exercise_kind || "exercise");
      if (config.problem) form.append("problem", config.problem);
```

JSON branch:
```javascript
        exercise_kind: config.exercise_kind || "exercise",
      };
      if (config.problem) payload.problem = config.problem;
```

(Place the JSON `if` immediately after the object literal closes and before `if (conversationId) payload.conversation_id = conversationId;`.)

- [ ] **Step 7: Bump the cache-buster**

In `main_ui/templates/embed.html` line 2, change `v='7'` to `v='8'`:

```jinja
{% block chat_js_src %}{{ url_for('static', filename='js/chat.js', v='8') }}{% endblock %}
```

- [ ] **Step 8: Run tests**

Run: `python -m main_ui.routes.test_problem_focus`
Expected: PASS.

Run the no-focus regressions: `python -m main_ui.routes.test_embed_practice` and `python -m main_ui.routes.test_chat_practice`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add main_ui/routes/_validation.py main_ui/routes/embed.py main_ui/routes/chat.py main_ui/static/js/chat.js main_ui/templates/embed.html main_ui/routes/test_problem_focus.py
git commit -m "feat(main_ui): accept and persist problem focus param"
```

---

### Task 6: sandbox_ui web layer — parity with main_ui

**Files:**
- Modify: `sandbox_ui/routes/_validation.py` (import `subproblem_label`; add `validate_problem`)
- Modify: `sandbox_ui/routes/embed.py` (`_render_embed`, `embed()`)
- Modify: `sandbox_ui/routes/chat.py` (`chat()` — validate inside the `if convo_id is None:` block, persist, snapshot, thread)
- Modify: `sandbox_ui/static/js/chat.js` (add `problem` to the `fields` dict, guarded)
- Modify: `sandbox_ui/templates/embed.html` (bump `chat.js` `v='23'` → `v='24'`; and update the sandbox chat.js cache-version memory note)
- Test: `sandbox_ui/routes/test_problem_focus.py` (Create)

**Interfaces:**
- Consumes: same as Task 5, against sandbox_ui's modules.
- Produces: sandbox parity — `validate_problem`, `problem` in `tutor_config`, `focus_problem` persisted + threaded.

**Note — sandbox validation placement:** sandbox `chat.py` validates context **only when starting a new conversation** (inside `if convo_id is None:`, lines 201-216). `validate_problem` must go inside that block too, so continuations don't re-validate a stored focus.

**Note — sandbox `tutor_config` uses camelCase `exerciseKind`** but `course`/`exercise`/`tutor`/`role` are plain. Use the key **`problem`** (matching main_ui and what `chat.js` reads as `config.problem`).

- [ ] **Step 1: Write the failing test**

Create `sandbox_ui/routes/test_problem_focus.py` (identical shape to Task 5's, but importing sandbox's app):

```python
"""Flask test-client checks for the problem-focus param in sandbox_ui.

Run:
    python -m sandbox_ui.routes.test_problem_focus
"""
from __future__ import annotations

from sandbox_ui.run_app import app
from utils.curriculum import list_subproblems

COURSE = "supply_chain_design"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()

    subs = list_subproblems(COURSE, "1", "practice")
    if not subs:
        print("SKIP - no sub-problems for", COURSE, "practice 1")
        return 0
    n = subs[-1][0]

    r = client.get(f"/embed?course={COURSE}&practice=1&problem={n}")
    ok &= _check("valid problem renders", r.status_code == 200, r.status_code)
    ok &= _check("problem echoed in config",
                 (f'"problem": {n}'.encode() in r.data) or (f'"problem": "{n}"'.encode() in r.data))

    ok &= _check("out-of-range problem -> 404",
                 client.get(f"/embed?course={COURSE}&practice=1&problem=999").status_code == 404)
    ok &= _check("non-integer problem -> 404",
                 client.get(f"/embed?course={COURSE}&practice=1&problem=abc").status_code == 404)
    ok &= _check("no problem still renders",
                 client.get(f"/embed?course={COURSE}&practice=1").status_code == 200)

    bad = client.post("/api/chat", json={
        "text": "hi", "course": COURSE, "exercise": "1",
        "exercise_kind": "practice", "problem": "999",
    })
    ok &= _check("chat bad problem -> 404", bad.status_code == 404, bad.status_code)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m sandbox_ui.routes.test_problem_focus`
Expected: FAIL.

- [ ] **Step 3: Add `validate_problem` to sandbox `_validation.py`**

Add `subproblem_label` to the `utils.curriculum` imports, then add the **same** `validate_problem` function as Task 5 Step 3 (identical body — sandbox has its own `_err`).

- [ ] **Step 4: Wire sandbox `embed.py`**

Import `validate_problem`. Mirror Task 5 Step 4 exactly, except `tutor_config` uses `exerciseKind` (leave that key as-is) and add `problem` the same way:

```python
def _render_embed(*, course: str, exercise: str, tutor: str, exercise_kind: str = "exercise", role: str = DEFAULT_ROLE, problem: str | None = None):
    """Render the embed.html chat widget for the given course/exercise|practice/tutor/role/problem context."""
    tutor_config = {
        "course": course,
        "exercise": exercise,
        "tutor": tutor,
        "role": role,
        "exerciseKind": exercise_kind,
    }
    if problem:
        tutor_config["problem"] = int(problem)
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

In `embed()`, after `resolve_embed_selection` and before `validate_tutor`:

```python
    problem = request.args.get("problem")
    err = validate_problem(course, number, kind, problem)
    if err:
        return _bad_param(err)

    err = validate_tutor(tutor)
    if err:
        return _bad_param(err)

    return _render_embed(course=course, exercise=number, tutor=tutor, exercise_kind=kind, role=role, problem=problem)
```

- [ ] **Step 5: Wire sandbox `chat.py`**

Import `validate_problem`. Read `problem` from `src` up near the other `src.get` reads (e.g. after the `exercise`/`raw_kind` block, ~line 150):

```python
    problem = src.get("problem")
```

Validate it **inside** the `if convo_id is None:` block, after `validate_selection` (line 210-213):

```python
        err = validate_selection(course, exercise, exercise_kind)
        if err:
            return _bad_param(err)

        err = validate_problem(course, exercise, exercise_kind, problem)
        if err:
            return _bad_param(err)
```

Pass `focus_problem` to `find_or_create_conversation` (after `exercise_kind=exercise_kind,`):

```python
        convo = find_or_create_conversation(
            db,
            session_id=g.session_id,
            conversation_id=convo_id,
            course=course,
            exercise_number=exercise,
            exercise_kind=exercise_kind,
            focus_problem=int(problem) if problem else None,
            tutor_prompt=tutor,
            username=username,
            lectures_enabled=lectures_enabled,
            context_mode=context_mode,
            provider=provider,
        )
```

Snapshot after `stream_exercise_kind` (line 314):

```python
    stream_exercise_kind = convo.exercise_kind or "exercise"
    stream_focus_problem = convo.focus_problem
```

Add to `stream_kwargs` (after `exercise_kind=stream_exercise_kind,`):

```python
        exercise_kind=stream_exercise_kind,
        focus_problem=stream_focus_problem,
```

- [ ] **Step 6: Send `problem` from sandbox `chat.js`**

In `sandbox_ui/static/js/chat.js`, the send builds a `fields` object (lines 1569-1580) then iterates it. Add `problem` guarded like the other optionals (after line 1579):

```javascript
    if (config.contextMode != null) fields.context_mode = config.contextMode;
    if (config.provider) fields.provider = config.provider;
    if (config.problem) fields.problem = config.problem;
    if (conversationId) fields.conversation_id = conversationId;
```

- [ ] **Step 7: Bump cache-buster + update the memory note**

In `sandbox_ui/templates/embed.html` line 68, change `v='23'` to `v='24'`:

```jinja
{% block chat_js_src %}{{ url_for('static', filename='js/chat.js', v='24') }}{% endblock %}
```

Update the sandbox chat.js cache-version memory file at `C:\Users\nishi\.claude\projects\d--asktim-llm-tutor-project\memory\sandbox-chatjs-cache-version.md` to note the new version (`24`).

- [ ] **Step 8: Run tests**

Run: `python -m sandbox_ui.routes.test_problem_focus`
Expected: PASS.

Run regressions: `python -m sandbox_ui.routes.test_embed_practice` and `python -m sandbox_ui.routes.test_chat_practice` (if present) / `python -m sandbox_ui.services.test_tutor_bridge_practice`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add sandbox_ui/routes/_validation.py sandbox_ui/routes/embed.py sandbox_ui/routes/chat.py sandbox_ui/static/js/chat.js sandbox_ui/templates/embed.html sandbox_ui/routes/test_problem_focus.py
git commit -m "feat(sandbox_ui): accept and persist problem focus param (parity with main_ui)"
```

---

### Task 7: Documentation — READMEs + route docstrings

**Files:**
- Modify: top-level `README.md` (embed-params section)
- Modify: `main_ui/routes/embed.py` and `sandbox_ui/routes/embed.py` (module docstrings)
- Modify: `main_ui/routes/chat.py` and `sandbox_ui/routes/chat.py` (request-shape docstrings)

**Interfaces:**
- Consumes: the finished behavior from Tasks 1-6.
- Produces: docs only — no code paths change.

- [ ] **Step 1: Find where the top-level README documents embed params**

Run: `grep -n "practice\|exercise=\|role=" README.md`
Locate the section listing `course`, `exercise`/`practice`, `role`.

- [ ] **Step 2: Document `problem` in the README**

Add a bullet next to the existing param docs, e.g.:

```markdown
- `problem=<n>` *(optional)* — focus a single sub-problem within the selected
  week file (`Practice Problem N:` / `Graded Assignment N:`). The whole file
  still loads; the tutor is told the student is working on problem `n` and
  treats the rest as reference. Persisted per conversation. An unknown `n`
  (or a non-integer) 404s.
```

- [ ] **Step 3: Update the four route docstrings**

In each `embed.py` module docstring, add a sentence after the `practice=<n>` description noting the optional `problem=<n>` focus param and that an invalid value 404s.

In each `chat.py` request-shape docstring (the JSON block), add:

```
      "problem": "N",                  optional; focus sub-problem in the file
```

- [ ] **Step 4: Sanity-check nothing else broke**

Run the full touched-test set:
```
python -m utils.test_subproblems
python -m ui_core.test_tutor_bridge_focus
python -m main_ui.db.test_focus_problem_migration
python -m main_ui.services.test_focus_problem_persist
python -m main_ui.routes.test_problem_focus
python -m sandbox_ui.routes.test_problem_focus
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md main_ui/routes/embed.py sandbox_ui/routes/embed.py main_ui/routes/chat.py sandbox_ui/routes/chat.py
git commit -m "docs: document the problem focus param across READMEs and routes"
```

---

## Self-Review Notes

- **Spec coverage:** Parser (§1) → Task 1. Validation (§2) → Tasks 5/6. embed.py (§3) → Tasks 5/6. chat.js (§4) → Tasks 5/6. Persistence column + migration + services (§5) → Tasks 3/4. chat.py (§6) → Tasks 5/6. Bridge directive + cache_key (§7) → Task 2. URL behavior (§8) → covered by Task 5/6 tests. READMEs → Task 7. Testing plan → per-task tests. Non-goals (no sibling-file load, no text extraction, no wizard wiring, no RAG change) → respected; none implemented.
- **Type consistency:** `list_subproblems` returns `list[tuple[int, str]]`; `subproblem_label` returns `str | None` and accepts int-or-digit-string `problem`. `validate_problem(course, number, kind, problem)` returns `dict | None`. `focus_problem` is `int | None` end-to-end (routes coerce `int(problem) if problem else None`; the column is `Integer`; the bridge reads `ctx.get("focus_problem")` and truthiness-guards). `tutor_config["problem"]` is an int (frontend guards on truthiness, so 0 is never a valid sub-problem number — sub-problems are 1..N).
- **Cache-buster:** main_ui `7`→`8`, sandbox_ui `23`→`24`; sandbox memory note updated in Task 6.
- **No-focus invariance:** every wiring point truthiness-guards `problem`/`focus_problem`, so absent focus is byte-identical to today (directive omitted, NULL persisted, cache-key tail is `None`, `tutor_config` key omitted, no `problem` field sent).
