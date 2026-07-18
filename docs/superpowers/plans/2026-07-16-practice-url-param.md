# Practice-problem URL Param Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `?practice=<n>` a first-class sibling of `?exercise=<n>` in the `/embed` URL for both `main_ui` and `sandbox_ui`, so a practice problem flows all the way into the tutor's context.

**Architecture:** Mirror the practice plumbing sandbox_ui already has into main_ui (validation, `exercise_kind` on the Conversation, chat handler, frontend), add practice-awareness to the *shared* `ui_core` tutor bridge (main_ui uses it directly; sandbox overrides it, so sandbox is untouched), and expose the URL param in both `/embed` routes with a both-params guard.

**Tech Stack:** Python 3.12, Flask, SQLAlchemy 2.x, Alembic (main_ui migrations), vanilla JS frontend. Tests are standalone `python -m <module>` scripts and Flask test-client scripts, matching the repo's existing `test_*.py` convention.

## Global Constraints

- `exercise_kind` is always one of exactly `"exercise"` or `"practice"`; anything else coerces to `"exercise"`.
- The problem number is stored in the existing `Conversation.exercise_number` column for BOTH kinds; `exercise_kind` disambiguates.
- A URL that supplies BOTH `exercise` and `practice` must return **HTTP 404** (`{"error": "invalid_param", ...}`), consistent with existing bad-param behavior.
- The tutor prompt stays locked to `DEFAULT_TUTOR` in production — do not honor `?tutor=`.
- New DB column ships as `TEXT NOT NULL DEFAULT 'exercise'` so existing rows are unaffected.
- The tutor-context block keeps the literal label `"Exercise:\n"` for practice too (matches sandbox's already-shipped behavior; the label is internal, never shown to students).
- Git commits in this repo omit the `Co-Authored-By: Claude` trailer.
- Per-app frontend naming: main_ui uses snake_case `exercise_kind` in its `tutor_config`/JS; sandbox_ui uses camelCase `exerciseKind` (its existing `chat.js` reads `config.exerciseKind`).

---

### Task 1: Shared bridge — make `build_assignment_text` + `cache_key` kind-aware

**Files:**
- Modify: `ui_core/tutor_bridge.py` (imports ~57-60; `cache_key` 249-255; `build_assignment_text` 269-300)
- Test: `ui_core/test_tutor_bridge_practice.py` (create)

**Interfaces:**
- Consumes: `utils.curriculum.practice_path`, `exercise_path`, `read_solution`.
- Produces: `TutorBridge.build_assignment_text(course, exercise, **ctx)` now honors `ctx["exercise_kind"]` (`"exercise"` default); `TutorBridge.cache_key(...)` includes the kind. main_ui (Task 5) relies on this by passing `exercise_kind` through `**ctx`.

- [ ] **Step 1: Write the failing test**

Create `ui_core/test_tutor_bridge_practice.py`:

```python
"""Standalone test: the base TutorBridge resolves practice files by kind.

Run:
    python -m ui_core.test_tutor_bridge_practice
"""
from __future__ import annotations

import shutil
from pathlib import Path

from ui_core.tutor_bridge import TutorBridge

_CURRICULUM = Path(__file__).resolve().parents[1] / "curriculum"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    course = "tmp_course_base_practice"
    exdir = _CURRICULUM / course / "exercises"
    prdir = _CURRICULUM / course / "practices"
    exdir.mkdir(parents=True, exist_ok=True)
    prdir.mkdir(parents=True, exist_ok=True)
    (exdir / "exercise_1.txt").write_text("EXERCISE ONE BODY", encoding="utf-8")
    (prdir / "practice_1.txt").write_text("PRACTICE ONE BODY", encoding="utf-8")
    ok = True
    try:
        bridge = TutorBridge()
        ex_text = bridge.build_assignment_text(course, "1", exercise_kind="exercise")
        pr_text = bridge.build_assignment_text(course, "1", exercise_kind="practice")
        ok &= _check("exercise kind resolves exercise file", "EXERCISE ONE BODY" in ex_text, ex_text)
        ok &= _check("practice kind resolves practice file", "PRACTICE ONE BODY" in pr_text, pr_text)
        ok &= _check("default kind is exercise", "EXERCISE ONE BODY" in bridge.build_assignment_text(course, "1"))
        k_ex = bridge.cache_key("tutor_07", course, "1", exercise_kind="exercise")
        k_pr = bridge.cache_key("tutor_07", course, "1", exercise_kind="practice")
        ok &= _check("cache_key differs by kind", k_ex != k_pr, f"{k_ex} == {k_pr}")
    finally:
        shutil.rmtree(_CURRICULUM / course, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m ui_core.test_tutor_bridge_practice`
Expected: FAIL — `practice kind resolves practice file` (base still reads `exercise_path`) and `cache_key differs by kind`.

- [ ] **Step 3: Add the `practice_path` import**

In `ui_core/tutor_bridge.py`, the existing curriculum import block (~lines 55-61) imports `exercise_path`, `read_solution`, etc. Add `practice_path`:

```python
    exercise_path,
    practice_path,
    read_solution,
```

- [ ] **Step 4: Make `cache_key` kind-aware**

Replace the `cache_key` body (lines 249-255) so the kind is part of the key:

```python
        return (
            tutor,
            course,
            exercise,
            ctx.get("exercise_kind", "exercise"),
            ctx.get("context_mode", "full_context"),
            _resolve_provider(ctx.get("provider")),
        )
```

- [ ] **Step 5: Resolve the problem file + solution by kind in `build_assignment_text`**

In `build_assignment_text`, replace the line that reads the exercise text (line 270):

```python
        mode = ctx.get("context_mode", "full_context")
        kind = ctx.get("exercise_kind", "exercise")
        problem_path = (
            practice_path(course, exercise)
            if kind == "practice"
            else exercise_path(course, exercise)
        )
        exercise_text = problem_path.read_text(encoding="utf-8").strip()
```

And replace the solution read (line 297) so it uses the same kind:

```python
        solution = read_solution(course, exercise, kind=kind)
```

Leave the `parts.append("Exercise:\n" + exercise_text)` label unchanged (Global Constraints).

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m ui_core.test_tutor_bridge_practice`
Expected: PASS (all lines).

- [ ] **Step 7: Verify sandbox is unaffected**

Run: `python -m sandbox_ui.services.test_tutor_bridge_practice`
Expected: PASS (sandbox overrides `build_assignment_text`, so its behavior is unchanged).

- [ ] **Step 8: Commit**

```bash
git add ui_core/tutor_bridge.py ui_core/test_tutor_bridge_practice.py
git commit -m "feat(ui_core): make shared tutor bridge resolve practice files by kind"
```

---

### Task 2: main_ui validation — `validate_practice`, `validate_selection`, `resolve_embed_selection`

**Files:**
- Modify: `main_ui/routes/_validation.py`
- Test: `main_ui/routes/test_validation_practice.py` (create)

**Interfaces:**
- Consumes: `utils.curriculum.practice_exists`.
- Produces:
  - `validate_practice(course, practice) -> dict | None`
  - `validate_selection(course, number, kind) -> dict | None`
  - `resolve_embed_selection(course, raw_exercise, raw_practice, default_exercise) -> tuple[str | None, str | None, dict | None]` returning `(number, kind, err)`. Task 6 (embed) and Task 7 (chat) consume these.

- [ ] **Step 1: Write the failing test**

Create `main_ui/routes/test_validation_practice.py`:

```python
"""Standalone test for practice validation + selection resolution in main_ui.

Run:
    python -m main_ui.routes.test_validation_practice
"""
from __future__ import annotations

import shutil

import main_ui.routes._validation as V


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    course = "tmp_course_main_practice"
    prdir = V._CURRICULUM_DIR / course / "practices"
    prdir.mkdir(parents=True, exist_ok=True)
    (prdir / "practice_1.txt").write_text("PRACTICE BODY", encoding="utf-8")
    exdir = V._CURRICULUM_DIR / course / "exercises"
    exdir.mkdir(parents=True, exist_ok=True)
    (exdir / "exercise_1.txt").write_text("EXERCISE BODY", encoding="utf-8")
    ok = True
    try:
        ok &= _check("validate_practice ok", V.validate_practice(course, "1") is None)
        ok &= _check("validate_practice padded ok", V.validate_practice(course, "01") is None)
        ok &= _check("validate_practice missing file", V.validate_practice(course, "99") is not None)
        ok &= _check("validate_practice bad format", V.validate_practice(course, "x") is not None)
        ok &= _check("validate_selection practice", V.validate_selection(course, "1", "practice") is None)
        ok &= _check("validate_selection exercise", V.validate_selection(course, "1", "exercise") is None)

        n, k, err = V.resolve_embed_selection(course, None, "1", "01")
        ok &= _check("resolve practice", (n, k) == ("1", "practice") and err is None, (n, k, err))
        n, k, err = V.resolve_embed_selection(course, "1", None, "01")
        ok &= _check("resolve exercise", (n, k) == ("1", "exercise") and err is None, (n, k, err))
        n, k, err = V.resolve_embed_selection(course, None, None, "1")
        ok &= _check("resolve default exercise", (n, k) == ("1", "exercise") and err is None, (n, k, err))
        n, k, err = V.resolve_embed_selection(course, "1", "1", "01")
        ok &= _check("resolve both -> error", err is not None and n is None, (n, k, err))
    finally:
        shutil.rmtree(V._CURRICULUM_DIR / course, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m main_ui.routes.test_validation_practice`
Expected: FAIL with `AttributeError: module ... has no attribute 'validate_practice'`.

- [ ] **Step 3: Add the practice import + validators**

In `main_ui/routes/_validation.py`, add to the imports (after line 13):

```python
from utils.curriculum import practice_exists as _practice_exists
```

Add these functions after `validate_exercise` (after line 63):

```python
def validate_practice(course, practice) -> dict | None:
    """Return None if *practice* is a digit string with a file under *course*, else a failure dict."""
    if not practice:
        return _err("practice", practice, "missing")
    if not (isinstance(practice, str) and practice.isdigit()):
        return _err(
            "practice", practice, "must be a non-negative integer (e.g. 4)"
        )
    if not _practice_exists(course, practice):
        return _err(
            "practice", practice,
            f"no practice_{practice}.txt under curriculum/{course}/practices/",
        )
    return None


def validate_selection(course, number, kind) -> dict | None:
    """Validate a (kind, number) selection against the matching content folder."""
    if kind == "practice":
        return validate_practice(course, number)
    return validate_exercise(course, number)


def resolve_embed_selection(course, raw_exercise, raw_practice, default_exercise):
    """Resolve (number, kind) from embed query params.

    Returns ``(number, kind, err)``. ``err`` is a failure dict (mapped to 404 by
    the route) when both params are supplied or the resolved value is invalid;
    ``number``/``kind`` are None on the both-params error.
    """
    if raw_exercise and raw_practice:
        return None, None, _err(
            "selection", "exercise+practice",
            "cannot specify both exercise and practice",
        )
    if raw_practice:
        return raw_practice, "practice", validate_practice(course, raw_practice)
    number = raw_exercise or default_exercise
    return number, "exercise", validate_exercise(course, number)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m main_ui.routes.test_validation_practice`
Expected: PASS (all lines).

- [ ] **Step 5: Commit**

```bash
git add main_ui/routes/_validation.py main_ui/routes/test_validation_practice.py
git commit -m "feat(main_ui): add practice validation and embed-selection resolver"
```

---

### Task 3: main_ui DB — `exercise_kind` column + Alembic migration

**Files:**
- Modify: `main_ui/db/models.py:40` (Conversation)
- Create: `main_ui/db/migrations/versions/<autogen>_add_exercise_kind.py`
- Test: `main_ui/db/test_exercise_kind_column.py` (create)

**Interfaces:**
- Produces: `Conversation.exercise_kind` (str, default `"exercise"`). Task 4 (service) writes it; Task 7 (chat) reads it back.

- [ ] **Step 1: Write the failing test**

Create `main_ui/db/test_exercise_kind_column.py`:

```python
"""Standalone test: main_ui Conversation has exercise_kind defaulting to 'exercise'.

Run:
    python -m main_ui.db.test_exercise_kind_column
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from main_ui.db.models import Base, Conversation


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    ok = True
    with Session(engine) as s:
        c = Conversation(
            session_id="sess", course="c", exercise_number="1", tutor_prompt="tutor_07"
        )
        s.add(c)
        s.commit()
        ok &= _check("defaults to exercise", c.exercise_kind == "exercise", c.exercise_kind)
        c2 = Conversation(
            session_id="s2", course="c", exercise_number="7",
            tutor_prompt="tutor_07", exercise_kind="practice",
        )
        s.add(c2)
        s.commit()
        ok &= _check("stores practice", c2.exercise_kind == "practice", c2.exercise_kind)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m main_ui.db.test_exercise_kind_column`
Expected: FAIL — `TypeError: 'exercise_kind' is an invalid keyword argument for Conversation` (or attribute missing).

- [ ] **Step 3: Add the column to the model**

In `main_ui/db/models.py`, add after the `exercise_number` column (line 40):

```python
    # Which content kind exercise_number refers to: "exercise" (graded, default)
    # or "practice". Additive column (server default 'exercise'); legacy rows read
    # back as exercises. Mirrors sandbox_ui's Conversation.exercise_kind.
    exercise_kind: Mapped[str] = mapped_column(
        Text, nullable=False, default="exercise", server_default="exercise"
    )
```

(`Text` and `mapped_column` are already imported in this file.)

- [ ] **Step 4: Run the model test to verify it passes**

Run: `python -m main_ui.db.test_exercise_kind_column`
Expected: PASS.

- [ ] **Step 5: Generate the Alembic migration skeleton**

Run: `alembic -c main_ui/db/migrations/alembic.ini revision -m "add exercise_kind"`
This creates a new file under `main_ui/db/migrations/versions/` with the correct `revision`/`down_revision` wired to the current head. Note the created path.

- [ ] **Step 6: Fill in the migration body**

In the generated file, set the `upgrade`/`downgrade` bodies (keep the auto-generated `revision`/`down_revision`/imports):

```python
def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "exercise_kind",
            sa.Text(),
            nullable=False,
            server_default="exercise",
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "exercise_kind")
```

- [ ] **Step 7: Apply the migration against a throwaway sqlite DB to verify it runs**

Run:
```bash
DATABASE_URL="sqlite:///./_migtest.db" alembic -c main_ui/db/migrations/alembic.ini upgrade head && rm -f _migtest.db
```
Expected: ends with `Running upgrade ... add exercise_kind`, no error.

- [ ] **Step 8: Commit**

```bash
git add main_ui/db/models.py main_ui/db/migrations/versions/ main_ui/db/test_exercise_kind_column.py
git commit -m "feat(main_ui): add exercise_kind column + migration to conversations"
```

---

### Task 4: main_ui conversation service — thread `exercise_kind`

**Files:**
- Modify: `main_ui/services/conversation.py` (`find_or_create_conversation` 30-55; `list_conversations_for_username` 135-139)
- Test: `main_ui/services/test_conversation_practice.py` (create)

**Interfaces:**
- Consumes: `Conversation.exercise_kind` (Task 3), shared `find_or_create_conversation(..., extra_fields=...)`.
- Produces: `find_or_create_conversation(..., exercise_kind="exercise")` persists the kind; per-conversation history summaries include `exercise_kind`. Task 7 calls this; Task 8 reads the summary key.

- [ ] **Step 1: Write the failing test**

Create `main_ui/services/test_conversation_practice.py`:

```python
"""Standalone test: main_ui find_or_create_conversation persists exercise_kind.

Run:
    python -m main_ui.services.test_conversation_practice
"""
from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from main_ui.db.models import Base
from main_ui.services import conversation as svc


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    ok = True
    with Session(engine) as s:
        convo = svc.find_or_create_conversation(
            s, session_id="sess", conversation_id=None, course="c",
            exercise_number="7", exercise_kind="practice", tutor_prompt="tutor_07",
        )
        s.commit()
        ok &= _check("persists practice kind", convo.exercise_kind == "practice", convo.exercise_kind)

        convo2 = svc.find_or_create_conversation(
            s, session_id="sess2", conversation_id=None, course="c",
            exercise_number="3", tutor_prompt="tutor_07",
        )
        s.commit()
        ok &= _check("defaults to exercise", convo2.exercise_kind == "exercise", convo2.exercise_kind)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m main_ui.services.test_conversation_practice`
Expected: FAIL — `find_or_create_conversation() got an unexpected keyword argument 'exercise_kind'`.

- [ ] **Step 3: Thread `exercise_kind` through `find_or_create_conversation`**

In `main_ui/services/conversation.py`, replace `find_or_create_conversation` (lines 30-55) with:

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
        extra_fields={"exercise_kind": exercise_kind},
    )
```

- [ ] **Step 4: Add `exercise_kind` to the history summary**

In `main_ui/services/conversation.py`, add a summarize hook and pass it to the list call. Add before `list_conversations_for_username`:

```python
def _summarize_extra(c: Conversation) -> dict:
    """main_ui summary key: the conversation's exercise_kind (for sidebar labels)."""
    return {"exercise_kind": c.exercise_kind or "exercise"}
```

Then change the body of `list_conversations_for_username` to pass it:

```python
    return _shared.list_conversations_for_username(
        db, username, models=_MODELS, summarize_extra=_summarize_extra
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m main_ui.services.test_conversation_practice`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add main_ui/services/conversation.py main_ui/services/test_conversation_practice.py
git commit -m "feat(main_ui): persist exercise_kind + expose it in history summaries"
```

---

### Task 5: main_ui tutor-bridge wrapper — accept `exercise_kind`

**Files:**
- Modify: `main_ui/services/tutor_bridge.py` (`build_assignment_text` 23-25; `get_tutor_reply` 28-59; `stream_tutor_reply` 62-98)
- Test: `main_ui/services/test_tutor_bridge_practice.py` (create)

**Interfaces:**
- Consumes: kind-aware base bridge (Task 1).
- Produces: `stream_tutor_reply(..., exercise_kind="exercise")` and `get_tutor_reply(..., exercise_kind="exercise")` forward the kind into the bridge `**ctx`. Task 7 passes `exercise_kind` here.

- [ ] **Step 1: Write the failing test**

Create `main_ui/services/test_tutor_bridge_practice.py`:

```python
"""Standalone test: main_ui bridge wrapper forwards exercise_kind to build_assignment_text.

Run:
    python -m main_ui.services.test_tutor_bridge_practice
"""
from __future__ import annotations

import shutil
from pathlib import Path

from main_ui.services import tutor_bridge as tb

_CURRICULUM = Path(__file__).resolve().parents[2] / "curriculum"


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    course = "tmp_course_mainbridge_practice"
    prdir = _CURRICULUM / course / "practices"
    prdir.mkdir(parents=True, exist_ok=True)
    (prdir / "practice_1.txt").write_text("PRACTICE BODY", encoding="utf-8")
    ok = True
    try:
        text = tb.build_assignment_text(course, "1", exercise_kind="practice")
        ok &= _check("wrapper forwards practice kind", "PRACTICE BODY" in text, text)
    finally:
        shutil.rmtree(_CURRICULUM / course, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m main_ui.services.test_tutor_bridge_practice`
Expected: FAIL — `build_assignment_text() got an unexpected keyword argument 'exercise_kind'`.

- [ ] **Step 3: Add `exercise_kind` to the wrapper functions**

In `main_ui/services/tutor_bridge.py`, replace `build_assignment_text` (23-25):

```python
def build_assignment_text(course: str, exercise: str, *, exercise_kind: str = "exercise") -> str:
    """Return the assignment text for a course/exercise|practice via the shared bridge."""
    return _bridge.build_assignment_text(course, exercise, exercise_kind=exercise_kind)
```

In `get_tutor_reply`, add `exercise_kind: str = "exercise",` to the signature (after `images`) and pass `exercise_kind=exercise_kind` into the `_bridge.get_tutor_reply(...)` call.

In `stream_tutor_reply`, add `exercise_kind: str = "exercise",` to the signature (after `images`) and pass `exercise_kind=exercise_kind` into the `_bridge.stream_tutor_reply(...)` call.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m main_ui.services.test_tutor_bridge_practice`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add main_ui/services/tutor_bridge.py main_ui/services/test_tutor_bridge_practice.py
git commit -m "feat(main_ui): forward exercise_kind through the tutor-bridge wrapper"
```

---

### Task 6: main_ui `/embed` route — practice param, both-params guard, kind in config

**Files:**
- Modify: `main_ui/routes/embed.py`
- Test: `main_ui/routes/test_embed_practice.py` (create)

**Interfaces:**
- Consumes: `resolve_embed_selection` (Task 2).
- Produces: `/embed?practice=<n>` renders with `tutor_config["exercise_kind"] = "practice"`; both-params → 404. Task 8 reads `config.exercise_kind` in JS.

- [ ] **Step 1: Write the failing test**

Create `main_ui/routes/test_embed_practice.py`:

```python
"""Flask test-client checks for practice URL handling in main_ui /embed.

Run:
    python -m main_ui.routes.test_embed_practice
"""
from __future__ import annotations

from main_ui.run_app import app
from main_ui.routes._validation import DEFAULT_COURSE
from main_ui.routes import _validation as V


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()

    # Pick a real practice number available for DEFAULT_COURSE, else skip that leg.
    practices = V.list_practice(DEFAULT_COURSE) if hasattr(V, "list_practice") else V._discover_practice(DEFAULT_COURSE)
    both = client.get(f"/embed?course={DEFAULT_COURSE}&exercise=1&practice=1")
    ok &= _check("both params -> 404", both.status_code == 404, both.status_code)

    if practices:
        n = practices[0]
        r = client.get(f"/embed?course={DEFAULT_COURSE}&practice={n}")
        ok &= _check("valid practice renders", r.status_code == 200, r.status_code)
        ok &= _check("kind in page config", b'"exercise_kind": "practice"' in r.data or b'"exercise_kind":"practice"' in r.data)
    else:
        print("SKIP - DEFAULT_COURSE has no practice files")

    bad = client.get(f"/embed?course={DEFAULT_COURSE}&practice=9999")
    ok &= _check("invalid practice -> 404", bad.status_code == 404, bad.status_code)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

Note: `main_ui/routes/_validation.py` has no `list_practice` today; add a thin `list_practice` there OR the test falls back to `_discover_practice`. To keep it clean, add `list_practice` in this task's Step 3.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m main_ui.routes.test_embed_practice`
Expected: FAIL — both-params returns 200 (param ignored today) instead of 404.

- [ ] **Step 3: Add a `list_practice` helper to `_validation.py`**

In `main_ui/routes/_validation.py`, add the import (near line 13):

```python
from utils.curriculum import discover_practice as _discover_practice
```

and the helper (after `resolve_embed_selection`):

```python
def list_practice(course) -> list[str]:
    """Non-padded practice-problem numbers for a course, sorted numerically."""
    if not course:
        return []
    return _discover_practice(course)
```

- [ ] **Step 4: Rewrite the `/embed` route to resolve exercise/practice**

In `main_ui/routes/embed.py`, update the imports to include the resolver, `_render_embed` to accept a kind, and the `embed()` view.

Update imports (12-23) to add `resolve_embed_selection`:

```python
from main_ui.routes._validation import (
    DEFAULT_COURSE,
    DEFAULT_EXERCISE,
    DEFAULT_TUTOR,
    load_course_name,
    resolve_embed_selection,
    validate_course,
    validate_tutor,
)
```

Change `_render_embed` (34-46) to carry the kind into `tutor_config`:

```python
def _render_embed(*, course: str, exercise: str, tutor: str, exercise_kind: str = "exercise"):
    """Render ``embed.html`` for the given course/exercise|practice/tutor context."""
    tutor_config = {
        "course": course,
        "exercise": exercise,
        "tutor": tutor,
        "exercise_kind": exercise_kind,
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

Replace the `embed()` view (59-84) to resolve and reject both:

```python
@embed_bp.get("/embed")
def embed():
    """Resolve course + exercise|practice from query params, validate, and render.

    `exercise` and `practice` are mutually exclusive; supplying both 404s. A
    missing number falls back to the default exercise; an explicitly invalid
    value 404s.
    """
    course = request.args.get("course") or DEFAULT_COURSE
    tutor = DEFAULT_TUTOR  # production is locked to a single tutor prompt

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

    return _render_embed(course=course, exercise=number, tutor=tutor, exercise_kind=kind)
```

(The `index()` view for `/` stays as-is; it renders the default exercise with the default `exercise_kind="exercise"`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m main_ui.routes.test_embed_practice`
Expected: PASS (or SKIP for the render leg if DEFAULT_COURSE has no practices — `cities_and_climate_change`; the both-params and invalid-practice legs still assert 404).

- [ ] **Step 6: Commit**

```bash
git add main_ui/routes/embed.py main_ui/routes/_validation.py main_ui/routes/test_embed_practice.py
git commit -m "feat(main_ui): accept ?practice= in /embed, reject exercise+practice together"
```

---

### Task 7: main_ui `/api/chat` route — read/validate/store/stream `exercise_kind`

**Files:**
- Modify: `main_ui/routes/chat.py` (imports 38-43; param read ~145-159; find_or_create ~189-197; stream capture ~258-284)
- Test: `main_ui/routes/test_chat_practice.py` (create)

**Interfaces:**
- Consumes: `validate_selection` (Task 2), `find_or_create_conversation(..., exercise_kind=...)` (Task 4), `stream_tutor_reply(..., exercise_kind=...)` (Task 5).
- Produces: a chat turn started with `exercise_kind="practice"` persists that kind and streams practice context.

- [ ] **Step 1: Write the failing test**

Create `main_ui/routes/test_chat_practice.py`:

```python
"""Flask test-client check: /api/chat accepts exercise_kind=practice and stores it.

Run:
    python -m main_ui.routes.test_chat_practice
"""
from __future__ import annotations

from main_ui.run_app import app
from main_ui.routes._validation import DEFAULT_COURSE, list_practice


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()
    practices = list_practice(DEFAULT_COURSE)
    if not practices:
        print("SKIP - DEFAULT_COURSE has no practice files; validation path still exercised below")
    # Unknown practice number must be rejected as a bad param (404), proving the
    # chat route validates the practice selection rather than silently accepting it.
    r = client.post("/api/chat", json={
        "text": "hi", "course": DEFAULT_COURSE,
        "exercise": "99999", "exercise_kind": "practice",
    })
    ok &= _check("bad practice number -> 404", r.status_code == 404, r.status_code)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m main_ui.routes.test_chat_practice`
Expected: FAIL — currently the route validates with `validate_exercise` against the exercises folder, so a nonexistent practice number is not necessarily rejected as a practice; and `exercise_kind` is ignored. (If it happens to 404 for another reason, the later store step still needs the wiring below.)

- [ ] **Step 3: Import `validate_selection` in chat.py**

In `main_ui/routes/chat.py`, update the validation imports (38-43):

```python
from main_ui.routes._validation import (
    DEFAULT_TUTOR,
    validate_course,
    validate_selection,
    validate_tutor,
)
```

(`validate_exercise` is no longer needed here; remove it from the import.)

- [ ] **Step 4: Read `exercise_kind` and validate the selection**

In `main_ui/routes/chat.py`, after `exercise = src.get("exercise")` (line 146) add:

```python
    raw_kind = src.get("exercise_kind")
    exercise_kind = "practice" if str(raw_kind).strip().lower() == "practice" else "exercise"
```

Replace the `validate_exercise(course, exercise)` block (154-156) with:

```python
    err = validate_selection(course, exercise, exercise_kind)
    if err:
        return _bad_param(err)
```

- [ ] **Step 5: Persist and stream the kind**

Pass the kind when creating the conversation — in the `find_or_create_conversation(...)` call (189-197) add `exercise_kind=exercise_kind,`.

After `stream_tutor = convo.tutor_prompt` (line 261) add:

```python
    stream_exercise_kind = convo.exercise_kind or "exercise"
```

In the `stream_kwargs = dict(...)` block (275-284) add `exercise_kind=stream_exercise_kind,`.

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m main_ui.routes.test_chat_practice`
Expected: PASS (`bad practice number -> 404`).

- [ ] **Step 7: Regression-check the existing chat validation path**

Run: `python -m main_ui.routes.test_embed_practice` and `python -m main_ui.routes.test_validation_practice`
Expected: PASS (no regressions).

- [ ] **Step 8: Commit**

```bash
git add main_ui/routes/chat.py main_ui/routes/test_chat_practice.py
git commit -m "feat(main_ui): thread exercise_kind through /api/chat validate/store/stream"
```

---

### Task 8: main_ui frontend — send `exercise_kind`, label practice rows

**Files:**
- Modify: `main_ui/static/js/chat.js` (POST fields 871-895; `formatEntryHeader` 558-564)
- Verification: manual (browser), no JS test harness in repo.

**Interfaces:**
- Consumes: `config.exercise_kind` from `tutor_config` (Task 6); `c.exercise_kind` from the history summary (Task 4).

- [ ] **Step 1: Send `exercise_kind` on the multipart path**

In `main_ui/static/js/chat.js`, in the `FormData` block (after line 875 `form.append("tutor", config.tutor);`) add:

```javascript
      form.append("exercise_kind", config.exercise_kind || "exercise");
```

- [ ] **Step 2: Send `exercise_kind` on the JSON path**

In the JSON `payload` object (886-891) add the field:

```javascript
      const payload = {
        text: text,
        course: config.course,
        exercise: config.exercise,
        tutor: config.tutor,
        exercise_kind: config.exercise_kind || "exercise",
      };
```

- [ ] **Step 3: Label practice rows in the sidebar**

In `formatEntryHeader` (558-564), replace the label line so practice rows read "Practice N":

```javascript
  function formatEntryHeader(c) {
    // "Exercise 3 · May 19 · 8 messages" (or "Practice 3 ...") — strip leading
    // zeros from the number; show the most-recent-active date.
    const exNumber = parseInt(c.exercise_number, 10);
    const kindLabel = c.exercise_kind === "practice" ? "Practice" : "Exercise";
    const parts = [
      `${kindLabel} ${Number.isFinite(exNumber) ? exNumber : c.exercise_number}`,
    ];
```

- [ ] **Step 4: Manual verification**

Run the app locally (or rely on the deploy) and load, in a browser:
- `/embed?course=supply_chain_design&practice=7` → the tutor greets/answers about practice problem 7 (its text is in context).
- Send a message; open a new chat and confirm the sidebar row reads "Practice 7".
- `/embed?course=supply_chain_design&exercise=7` → still works, labeled "Exercise 7".
- `/embed?course=supply_chain_design&exercise=3&practice=7` → 404 page.

Note: `supply_chain_design` is the sandbox default and has `practice_1..10`; `main_ui`'s DEFAULT_COURSE (`cities_and_climate_change`) may have no practices, so use `supply_chain_design` for the practice smoke test.

- [ ] **Step 5: Commit**

```bash
git add main_ui/static/js/chat.js
git commit -m "feat(main_ui): send exercise_kind from the composer and label practice rows"
```

---

### Task 9: sandbox_ui `/embed` route — expose `?practice=` for the URL entry point

**Files:**
- Modify: `sandbox_ui/routes/_validation.py` (add `resolve_embed_selection`)
- Modify: `sandbox_ui/routes/embed.py`
- Test: `sandbox_ui/routes/test_embed_practice.py` (create)

**Interfaces:**
- Consumes: sandbox's existing `validate_practice`/`validate_exercise`.
- Produces: `/embed?practice=<n>` renders with `tutor_config["exerciseKind"] = "practice"` (camelCase, matching sandbox's `chat.js`); both-params → 404. sandbox `chat.js` already reads `config.exerciseKind` and sends `exercise_kind`, and its chat route already stores it — so no sandbox JS/chat/DB change is needed.

- [ ] **Step 1: Write the failing test**

Create `sandbox_ui/routes/test_embed_practice.py`:

```python
"""Flask test-client checks for practice URL handling in sandbox_ui /embed.

Run:
    python -m sandbox_ui.routes.test_embed_practice
"""
from __future__ import annotations

from sandbox_ui.run_app import app
from sandbox_ui.routes._validation import DEFAULT_COURSE, list_practice


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    client = app.test_client()
    both = client.get(f"/embed?course={DEFAULT_COURSE}&exercise=1&practice=1")
    ok &= _check("both params -> 404", both.status_code == 404, both.status_code)

    practices = list_practice(DEFAULT_COURSE)
    if practices:
        n = practices[0]
        r = client.get(f"/embed?course={DEFAULT_COURSE}&practice={n}")
        ok &= _check("valid practice renders", r.status_code == 200, r.status_code)
        ok &= _check("kind in page config", b'"exerciseKind": "practice"' in r.data or b'"exerciseKind":"practice"' in r.data)
    else:
        print("SKIP - DEFAULT_COURSE has no practice files")

    bad = client.get(f"/embed?course={DEFAULT_COURSE}&practice=9999")
    ok &= _check("invalid practice -> 404", bad.status_code == 404, bad.status_code)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

`sandbox_ui`'s `run_app` app object is the import target; confirm it exposes `app` (it mirrors `main_ui/run_app.py`). If the attribute differs, import the app the same way sandbox's other route tests do.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m sandbox_ui.routes.test_embed_practice`
Expected: FAIL — both-params returns 200 today.

- [ ] **Step 3: Add `resolve_embed_selection` to sandbox `_validation.py`**

In `sandbox_ui/routes/_validation.py`, add after `validate_selection` (after line 178):

```python
def resolve_embed_selection(course, raw_exercise, raw_practice, default_exercise):
    """Resolve (number, kind) from embed query params.

    Returns ``(number, kind, err)``. ``err`` is a failure dict (mapped to 404 by
    the route) when both params are supplied or the resolved value is invalid;
    ``number``/``kind`` are None on the both-params error.
    """
    if raw_exercise and raw_practice:
        return None, None, _err(
            "selection", "exercise+practice",
            "cannot specify both exercise and practice",
        )
    if raw_practice:
        return raw_practice, "practice", validate_practice(course, raw_practice)
    number = raw_exercise or default_exercise
    return number, "exercise", validate_exercise(course, number)
```

- [ ] **Step 4: Wire the sandbox `/embed` route**

In `sandbox_ui/routes/embed.py`, add `resolve_embed_selection` to the `_validation` import block (15-24).

Change `_render_embed` (35-51) to accept and pass the kind (camelCase key for sandbox JS). Note: this function no longer carries a `syllabus` field (removed by the pinned-docs refactor) — do not reintroduce it:

```python
def _render_embed(*, course: str, exercise: str, tutor: str, exercise_kind: str = "exercise"):
    """Render the embed.html chat widget for the given course/exercise|practice/tutor context."""
    tutor_config = {
        "course": course,
        "exercise": exercise,
        "tutor": tutor,
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

Replace the `embed()` view (71-92) to resolve + reject both:

```python
@embed_bp.get("/embed")
def embed():
    """Render the chat widget from query params (exercise XOR practice), validating the resolved value."""
    course = request.args.get("course") or DEFAULT_COURSE
    tutor = DEFAULT_TUTOR  # sandbox is locked to a single tutor prompt

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

    return _render_embed(course=course, exercise=number, tutor=tutor, exercise_kind=kind)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m sandbox_ui.routes.test_embed_practice`
Expected: PASS (or SKIP for the render leg if sandbox's DEFAULT_COURSE has no practices — it is `supply_chain_design`, which DOES have practices, so it should PASS).

- [ ] **Step 6: Manual verification**

Load `sandbox` at `/embed?course=supply_chain_design&practice=7` and confirm the tutor has practice-7 context on the first message (before touching the wizard). Confirm `/embed?exercise=3&practice=7` → 404.

- [ ] **Step 7: Commit**

```bash
git add sandbox_ui/routes/embed.py sandbox_ui/routes/_validation.py sandbox_ui/routes/test_embed_practice.py
git commit -m "feat(sandbox_ui): accept ?practice= in /embed, reject exercise+practice together"
```

---

## Self-Review

**Spec coverage:**
- URL contract (`practice`, both→404, bare `/` unchanged, invalid→404): Tasks 6, 9 (routes) + Task 2 (resolver). ✓
- Data flow through validation/chat/DB/bridge: Tasks 2, 7, 3, 4, 1, 5. ✓
- Approach A (shared bridge kind-aware, sandbox untouched): Task 1 (+ Step 7 sandbox regression check). ✓
- DB column + Alembic migration on main_ui: Task 3. ✓
- Frontend threading + sidebar label: Tasks 8 (main), 9 (sandbox uses existing JS). ✓
- Testing (validation, bridge, routes): Tasks 1-9 each ship a test. ✓
- Out of scope (database_ui label, new content, per-kind prompt): not implemented, as specified. ✓

**Placeholder scan:** No TBD/TODO; every code + command step is concrete. The only conditional is the `SKIP` legs where a course lacks practice files — those still assert the 404 legs.

**Type consistency:** `exercise_kind: str` ("exercise"|"practice") is uniform across model (Task 3), service (Task 4), bridge wrapper (Task 5), routes (Tasks 6/7/9). `resolve_embed_selection(course, raw_exercise, raw_practice, default_exercise) -> (number, kind, err)` is identical in both apps (Tasks 2, 9). Frontend keys differ by app deliberately: main_ui `exercise_kind` (Task 6/8), sandbox `exerciseKind` (Task 9) — matching each app's existing `chat.js`.

## Known limitations (intentional)

- `turn_attachments` discovers curriculum *figures* by number; a practice problem with no figures gets none, and shares the numeric figure/RAG-week lookup with the same-numbered exercise. No practice-specific figures are wired — out of scope, no content depends on it today.
- `database_ui` still labels rows "Exercise N" (spec out-of-scope).
