# database_ui "Download data" CSV Export — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Download data" button to `database_ui` that opens a modal to multi-select courses and assignments, then downloads one CSV with a row per message.

**Architecture:** Two new read-only Flask routes (`/api/export/filters` to populate the picker, `/api/export.csv` to stream the file) backed by two new query functions in `database_ui/services/conversations.py`. A sidebar button opens a modal built in `download.js`; the modal builds a query string and navigates the browser to `/api/export.csv`, letting the browser save the file. No schema changes, no new Python dependencies (stdlib `csv`).

**Tech Stack:** Python 3.12, Flask, SQLAlchemy 2.x, stdlib `csv`, pytest (SQLite fixture DB), vanilla JS + CSS.

## Global Constraints

- **Read-only by construction:** never insert/update/commit. The per-request session always rolls back (`run_app.py`). All new queries are `SELECT` only.
- **No new Python dependencies:** CSV via stdlib `csv`; no `openpyxl`/`pandas`.
- **No schema/model changes:** `db/models.py` already maps every column used (`focus_problem`, `rating`, `cost_usd`, `usage_json`, `retrieved_context`).
- **Schema-drift handling:** DB errors that look like missing columns reuse the existing `_is_schema_drift` → HTTP 503 `{"error":"schema_outdated","message":"Redeploy askTIM-main to run migrations"}`, matching `/api/conversations`.
- **Commits:** Conventional Commits. Do NOT add a `Co-Authored-By: Claude` trailer (repo convention).
- **CSV format:** UTF-8 with a leading BOM (`﻿`); `Content-Type: text/csv; charset=utf-8`; `Content-Disposition: attachment`.
- **Selection identity:** an assignment is the pair `(course_key, exercise_number)`, encoded on the wire as `course_key::exercise_number`. The server re-derives all rows from these pairs; it never trusts a client-supplied conversation/message id list.
- **Column order (single source of truth `svc.EXPORT_COLUMNS`):**
  `conversation_id, course, course_name, exercise_number, exercise_kind, focus_problem, username, started_at, last_active_at, turn, role, content, pedagogical_reasoning, rating, model, cost_usd, usage_json, retrieved_context, image_count, created_at`

---

### Task 1: Test infrastructure + `list_export_filters` service

**Files:**
- Create: `database_ui/conftest.py` (pytest fixtures + seed helper)
- Create: `database_ui/tests/__init__.py` (empty)
- Create: `database_ui/tests/test_export_service.py`
- Modify: `database_ui/services/conversations.py`

**Interfaces:**
- Consumes: `database_ui.db.models` (`Conversation`, `Message`, `UploadedImage`, `Base`), `database_ui.db.session` (`engine`, `SessionLocal`), `database_ui.courses.course_display_name`.
- Produces:
  - `svc.list_export_filters(db: Session) -> list[dict]` — one dict per course `{"course": str, "course_name": str, "assignments": list[{"exercise_number": str, "exercise_kind": str}]}`, courses sorted by display name, assignments de-duplicated and sorted numerically-then-lexically.
  - conftest fixtures `db_session` (a `Session` on a throwaway SQLite DB with tables created) and `seed(db_session)` helper inserting a known fixture graph.

- [ ] **Step 1: Write `database_ui/conftest.py`**

The engine is built at import time from `DATABASE_UI_DATABASE_URL` (see `database_ui/db/session.py`), so the env var MUST be set before importing anything from `database_ui` — mirror `sandbox_ui/routes/conftest.py`.

```python
"""Pytest fixtures for database_ui tests.

Points database_ui at a throwaway on-disk SQLite DB *before* importing anything
from database_ui — the engine is built at import time from
``DATABASE_UI_DATABASE_URL`` (see ``database_ui/db/session.py``). This app never
creates schema in production (it only reads the live DB), so tests create the
tables themselves via ``Base.metadata.create_all`` on the throwaway DB.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone

import pytest

_tmp_db = tempfile.NamedTemporaryFile(prefix="database_ui_test_", suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_UI_DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"
os.environ.setdefault("DATABASE_UI_PASSWORD", "test-password")

from database_ui.db.models import Base, Conversation, Message, UploadedImage  # noqa: E402
from database_ui.db.session import SessionLocal, engine  # noqa: E402

Base.metadata.create_all(engine)


@pytest.fixture()
def db_session():
    """A SQLAlchemy session on the throwaway DB, wiped clean before each test."""
    session = SessionLocal()
    # Clean slate: delete in FK-safe order.
    session.query(UploadedImage).delete()
    session.query(Message).delete()
    session.query(Conversation).delete()
    session.commit()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def _dt(day: int) -> datetime:
    return datetime(2026, 5, day, 12, 0, tzinfo=timezone.utc)


def seed(session) -> dict:
    """Insert a known fixture graph and return ids for assertions.

    Two courses. supply_chain_design has exercises "1" and "2"; meaning_of_life
    has exercise "1". One conversation each; supply_chain ex "1" has a 2-message
    transcript (student turn + tutor turn) with one image on the student turn.
    """
    sc = Conversation(
        id=uuid.uuid4(), session_id="s1", username="stu@mit.edu",
        course="supply_chain_design", exercise_number="1", exercise_kind="exercise",
        focus_problem=None, tutor_prompt="p", started_at=_dt(1), last_active_at=_dt(3),
    )
    sc2 = Conversation(
        id=uuid.uuid4(), session_id="s2", username=None,
        course="supply_chain_design", exercise_number="2", exercise_kind="practice",
        focus_problem=4, tutor_prompt="p", started_at=_dt(1), last_active_at=_dt(2),
    )
    mol = Conversation(
        id=uuid.uuid4(), session_id="s3", username="stu@mit.edu",
        course="meaning_of_life", exercise_number="1", exercise_kind="exercise",
        focus_problem=None, tutor_prompt="p", started_at=_dt(1), last_active_at=_dt(1),
    )
    session.add_all([sc, sc2, mol])
    session.flush()

    m_student = Message(
        conversation_id=sc.id, turn=1, role="student", content="hello, comma, and\nnewline",
        pedagogical_reasoning=None, rating=0, cost_usd=None, usage_json=None,
        retrieved_context=None, created_at=_dt(3),
    )
    m_tutor = Message(
        conversation_id=sc.id, turn=1, role="tutor", content="answer",
        pedagogical_reasoning="because", rating=1, cost_usd=0.0123,
        usage_json='{"model": "gpt-5.4-2026-03-05", "input_tokens": 10}',
        retrieved_context='[{"source": "local:sc/ch1", "score": 0.9, "chars": 5, "text": "abcde"}]',
        created_at=_dt(3),
    )
    session.add_all([m_student, m_tutor])
    session.flush()
    session.add(UploadedImage(
        message_id=m_student.id, filename="f.png", mime_type="image/png",
        size_bytes=3, data=b"abc", created_at=_dt(3),
    ))
    session.commit()
    return {"sc_id": sc.id, "sc2_id": sc2.id, "mol_id": mol.id,
            "m_student_id": m_student.id, "m_tutor_id": m_tutor.id}
```

- [ ] **Step 2: Write the failing test for `list_export_filters`**

```python
# database_ui/tests/test_export_service.py
"""Tests for the read-only export query functions."""

from __future__ import annotations

from database_ui.conftest import seed
from database_ui.services import conversations as svc


def test_list_export_filters_groups_and_sorts(db_session):
    seed(db_session)
    courses = svc.list_export_filters(db_session)

    # Two courses, sorted by display name: "MIT 21A.157 The Meaning of Life"
    # sorts before "MIT CTL.SC2x Supply Chain Design".
    keys = [c["course"] for c in courses]
    assert keys == ["meaning_of_life", "supply_chain_design"]

    sc = next(c for c in courses if c["course"] == "supply_chain_design")
    assert sc["course_name"] == "MIT CTL.SC2x Supply Chain Design"
    exercises = [a["exercise_number"] for a in sc["assignments"]]
    assert exercises == ["1", "2"]  # numeric sort
    kinds = {a["exercise_number"]: a["exercise_kind"] for a in sc["assignments"]}
    assert kinds == {"1": "exercise", "2": "practice"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest database_ui/tests/test_export_service.py::test_list_export_filters_groups_and_sorts -v`
Expected: FAIL with `AttributeError: module ... has no attribute 'list_export_filters'`

- [ ] **Step 4: Implement `list_export_filters` (and helpers) in `services/conversations.py`**

Add `and_, or_` to the existing sqlalchemy import (`from sqlalchemy import and_, func, or_, select`). Append:

```python
# --- export -----------------------------------------------------------------

# Single source of truth for the export CSV's columns and their order. The route
# feeds this to csv.DictWriter as fieldnames; iter_export_rows yields dicts keyed
# by exactly these names.
EXPORT_COLUMNS = [
    "conversation_id", "course", "course_name", "exercise_number",
    "exercise_kind", "focus_problem", "username", "started_at",
    "last_active_at", "turn", "role", "content", "pedagogical_reasoning",
    "rating", "model", "cost_usd", "usage_json", "retrieved_context",
    "image_count", "created_at",
]


def _assignment_sort_key(exercise_number: str):
    """Sort assignments numerically when possible ("2" < "10"), else lexically."""
    try:
        return (0, float(exercise_number), "")
    except (TypeError, ValueError):
        return (1, 0.0, str(exercise_number))


def list_export_filters(db: Session) -> list[dict]:
    """Return the export picker's options: each course with its distinct assignments.

    Shape: ``[{"course", "course_name", "assignments": [{"exercise_number",
    "exercise_kind"}]}]``. Courses are sorted by display name; assignments are
    de-duplicated by ``exercise_number`` and sorted numerically-then-lexically.
    """
    stmt = select(
        Conversation.course,
        Conversation.exercise_number,
        Conversation.exercise_kind,
    ).distinct()
    kinds_by_course: dict[str, dict[str, str]] = {}
    for course, exercise_number, exercise_kind in db.execute(stmt).all():
        by_ex = kinds_by_course.setdefault(course, {})
        by_ex[exercise_number] = exercise_kind or "exercise"

    result: list[dict] = []
    for course in sorted(kinds_by_course, key=lambda k: course_display_name(k).lower()):
        by_ex = kinds_by_course[course]
        assignments = [
            {"exercise_number": ex, "exercise_kind": by_ex[ex]}
            for ex in sorted(by_ex, key=_assignment_sort_key)
        ]
        result.append({
            "course": course,
            "course_name": course_display_name(course),
            "assignments": assignments,
        })
    return result
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest database_ui/tests/test_export_service.py::test_list_export_filters_groups_and_sorts -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add database_ui/conftest.py database_ui/tests/__init__.py database_ui/tests/test_export_service.py database_ui/services/conversations.py
git commit -m "feat(database_ui): add list_export_filters query + test infra"
```

---

### Task 2: `iter_export_rows` service

**Files:**
- Modify: `database_ui/services/conversations.py`
- Modify: `database_ui/tests/test_export_service.py`

**Interfaces:**
- Consumes: `EXPORT_COLUMNS`, `Conversation`, `Message`, `UploadedImage`, `course_display_name`, `model_from_usage_json` (already imported at top of module).
- Produces: `svc.iter_export_rows(db: Session, pairs: set[tuple[str, str]]) -> Iterator[dict]` — yields one dict per message whose conversation matches a `(course, exercise_number)` pair. Keys are exactly `EXPORT_COLUMNS`. Ordered by `conversation.last_active_at DESC, message.turn, message.id`. Empty `pairs` yields nothing.

- [ ] **Step 1: Write the failing tests for `iter_export_rows`**

Append to `database_ui/tests/test_export_service.py`:

```python
def test_iter_export_rows_filters_and_columns(db_session):
    ids = seed(db_session)
    # Only supply_chain_design exercise "1" (the 2-message conversation).
    rows = list(svc.iter_export_rows(db_session, {("supply_chain_design", "1")}))

    assert len(rows) == 2
    # Every row has exactly the declared columns.
    for row in rows:
        assert set(row.keys()) == set(svc.EXPORT_COLUMNS)
    # Ordered by turn then id: student turn first, tutor second.
    assert [r["role"] for r in rows] == ["student", "tutor"]

    student, tutor = rows
    assert student["conversation_id"] == str(ids["sc_id"])
    assert student["course_name"] == "MIT CTL.SC2x Supply Chain Design"
    assert student["image_count"] == 1
    assert tutor["image_count"] == 0
    assert tutor["rating"] == 1
    assert tutor["model"] == "gpt-5.4-2026-03-05"  # parsed from usage_json
    assert tutor["cost_usd"] == 0.0123
    assert tutor["usage_json"].startswith("{")
    assert tutor["retrieved_context"].startswith("[")


def test_iter_export_rows_multiple_pairs_excludes_others(db_session):
    seed(db_session)
    pairs = {("supply_chain_design", "2"), ("meaning_of_life", "1")}
    rows = list(svc.iter_export_rows(db_session, pairs))
    # sc2 and mol conversations have no messages seeded -> zero rows, and the
    # 2-message sc/"1" conversation is NOT in the selection so it's excluded.
    assert rows == []


def test_iter_export_rows_empty_pairs_yields_nothing(db_session):
    seed(db_session)
    assert list(svc.iter_export_rows(db_session, set())) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest database_ui/tests/test_export_service.py -k iter_export_rows -v`
Expected: FAIL with `AttributeError: ... 'iter_export_rows'`

- [ ] **Step 3: Implement `iter_export_rows` (and helpers) in `services/conversations.py`**

Append to the export section:

```python
def _export_image_counts(db: Session, message_ids: list[int]) -> dict[int, int]:
    """Map message_id -> count of attached uploaded images (one grouped query)."""
    if not message_ids:
        return {}
    stmt = (
        select(UploadedImage.message_id, func.count(UploadedImage.id))
        .where(UploadedImage.message_id.in_(message_ids))
        .group_by(UploadedImage.message_id)
    )
    return {mid: int(n) for mid, n in db.execute(stmt).all()}


def _export_row(m: Message, c: Conversation, image_counts: dict[int, int]) -> dict:
    """Build one export CSV row (dict keyed by EXPORT_COLUMNS) from a message+convo."""
    return {
        "conversation_id": str(c.id),
        "course": c.course,
        "course_name": course_display_name(c.course),
        "exercise_number": c.exercise_number,
        "exercise_kind": c.exercise_kind or "exercise",
        "focus_problem": "" if c.focus_problem is None else c.focus_problem,
        "username": c.username or "",
        "started_at": c.started_at.isoformat() if c.started_at else "",
        "last_active_at": c.last_active_at.isoformat() if c.last_active_at else "",
        "turn": m.turn,
        "role": m.role,
        "content": m.content or "",
        "pedagogical_reasoning": m.pedagogical_reasoning or "",
        "rating": getattr(m, "rating", 0) or 0,
        "model": model_from_usage_json(getattr(m, "usage_json", None)) or "",
        "cost_usd": "" if getattr(m, "cost_usd", None) is None else m.cost_usd,
        "usage_json": getattr(m, "usage_json", None) or "",
        "retrieved_context": getattr(m, "retrieved_context", None) or "",
        "image_count": image_counts.get(m.id, 0),
        "created_at": m.created_at.isoformat() if m.created_at else "",
    }


def iter_export_rows(db: Session, pairs: set[tuple[str, str]]):
    """Yield one export row per message across conversations matching *pairs*.

    *pairs* is a set of ``(course_key, exercise_number)`` tuples. Rows are ordered
    by ``last_active_at`` (newest first), then ``turn``, then ``message.id`` — the
    same order the transcript view uses. Empty *pairs* yields nothing.
    """
    if not pairs:
        return
    conditions = [
        and_(Conversation.course == course, Conversation.exercise_number == exercise)
        for course, exercise in pairs
    ]
    stmt = (
        select(Message, Conversation)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(or_(*conditions))
        .order_by(Conversation.last_active_at.desc(), Message.turn, Message.id)
    )
    result = db.execute(stmt).all()
    image_counts = _export_image_counts(db, [m.id for m, _ in result])
    for m, c in result:
        yield _export_row(m, c, image_counts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest database_ui/tests/test_export_service.py -v`
Expected: PASS (all export-service tests)

- [ ] **Step 5: Commit**

```bash
git add database_ui/services/conversations.py database_ui/tests/test_export_service.py
git commit -m "feat(database_ui): add iter_export_rows CSV-row query"
```

---

### Task 3: Export routes (`/api/export/filters` + `/api/export.csv`)

**Files:**
- Modify: `database_ui/routes/database.py`
- Create: `database_ui/tests/test_export_routes.py`

**Interfaces:**
- Consumes: `svc.list_export_filters`, `svc.iter_export_rows`, `svc.EXPORT_COLUMNS`, existing `_is_schema_drift`.
- Produces:
  - `GET /api/export/filters` → `{"courses": [...]}` (200), or 503/500 on error.
  - `GET /api/export.csv?assignment=course::exercise&...` → `text/csv` attachment with BOM (200); 400 on empty/malformed selection.

- [ ] **Step 1: Write the failing route tests**

```python
# database_ui/tests/test_export_routes.py
"""Route tests for the CSV export endpoints."""

from __future__ import annotations

import pytest

from database_ui.conftest import seed
from database_ui.db.session import SessionLocal
from database_ui.run_app import create_app


@pytest.fixture()
def client():
    app = create_app()
    # Disable the auth gate so tests hit the API directly.
    app.config["DATABASE_UI_PASSWORD"] = None
    return app.test_client()


@pytest.fixture()
def seeded():
    from database_ui.db.models import Conversation, Message, UploadedImage
    session = SessionLocal()
    session.query(UploadedImage).delete()
    session.query(Message).delete()
    session.query(Conversation).delete()
    session.commit()
    ids = seed(session)
    session.close()
    return ids


def test_filters_endpoint_returns_courses(client, seeded):
    resp = client.get("/api/export/filters")
    assert resp.status_code == 200
    data = resp.get_json()
    keys = [c["course"] for c in data["courses"]]
    assert keys == ["meaning_of_life", "supply_chain_design"]


def test_export_csv_headers_and_bom(client, seeded):
    resp = client.get("/api/export.csv?assignment=supply_chain_design::1")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/csv")
    assert "attachment" in resp.headers["Content-Disposition"]
    body = resp.get_data(as_text=True)
    assert body.startswith("﻿")  # UTF-8 BOM
    # Header row present with the first and last declared columns.
    header_line = body.lstrip("﻿").splitlines()[0]
    assert header_line.startswith("conversation_id,")
    assert header_line.endswith(",created_at")
    # Two message rows for supply_chain_design exercise "1".
    assert body.count("\n") >= 2


def test_export_csv_filters_out_unselected(client, seeded):
    # Select only meaning_of_life "1" (no messages) -> header-only CSV.
    resp = client.get("/api/export.csv?assignment=meaning_of_life::1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True).lstrip("﻿")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) == 1  # header only


def test_export_csv_empty_selection_is_400(client, seeded):
    resp = client.get("/api/export.csv")
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "bad_selection"


def test_export_csv_malformed_pair_is_400(client, seeded):
    # No "::" separator -> not a valid pair -> empty selection -> 400.
    resp = client.get("/api/export.csv?assignment=supply_chain_design")
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest database_ui/tests/test_export_routes.py -v`
Expected: FAIL with 404s (routes not registered yet)

- [ ] **Step 3: Implement the routes in `routes/database.py`**

Add stdlib imports near the top (after `from uuid import UUID`):

```python
import csv
import io
```

Add the two routes (place them after `api_conversations`, before `api_conversation`):

```python
@database_bp.get("/api/export/filters")
def api_export_filters():
    """Return the export picker's course/assignment options as JSON."""
    try:
        courses = svc.list_export_filters(g.db)
    except SQLAlchemyError as exc:
        g.db.rollback()
        if _is_schema_drift(exc):
            current_app.logger.error("export filters failed on schema drift: %s", exc)
            return (
                jsonify({"error": "schema_outdated",
                         "message": "Redeploy askTIM-main to run migrations"}),
                503,
            )
        current_app.logger.exception("export filters query failed")
        return jsonify({"error": "query_failed", "message": "Could not load filters"}), 500
    return jsonify({"courses": courses})


@database_bp.get("/api/export.csv")
def api_export_csv():
    """Stream a CSV (one row per message) for the selected course/assignment pairs.

    Selection arrives as repeated ``assignment=<course>::<exercise>`` query args.
    Returns 400 when no valid pair is supplied; a valid-but-empty match returns a
    header-only CSV (not an error).
    """
    pairs = _parse_assignment_pairs(request.args.getlist("assignment"))
    if not pairs:
        return jsonify({"error": "bad_selection",
                        "message": "Select at least one assignment"}), 400
    try:
        rows = list(svc.iter_export_rows(g.db, pairs))
    except SQLAlchemyError as exc:
        g.db.rollback()
        if _is_schema_drift(exc):
            current_app.logger.error("export query failed on schema drift: %s", exc)
            return (
                jsonify({"error": "schema_outdated",
                         "message": "Redeploy askTIM-main to run migrations"}),
                503,
            )
        current_app.logger.exception("export query failed")
        return jsonify({"error": "query_failed", "message": "Could not export data"}), 500

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=svc.EXPORT_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    # Leading BOM so Excel opens the UTF-8 file with correct encoding.
    body = "﻿" + buf.getvalue()
    filename = f"asktim-export-{len(rows)}-msgs.csv"
    return Response(
        body,
        content_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

Add the pair parser near `_clamp_int` at the bottom of the file:

```python
def _parse_assignment_pairs(raw_values: list[str]) -> set[tuple[str, str]]:
    """Parse ``course::exercise`` query args into a set of (course, exercise) pairs.

    Values without a ``::`` separator, or with an empty side, are skipped — an
    all-skipped selection yields an empty set (the route turns that into a 400).
    """
    pairs: set[tuple[str, str]] = set()
    for raw in raw_values:
        if not raw or "::" not in raw:
            continue
        course, exercise = raw.split("::", 1)
        course, exercise = course.strip(), exercise.strip()
        if course and exercise:
            pairs.add((course, exercise))
    return pairs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest database_ui/tests/test_export_routes.py -v`
Expected: PASS (all route tests)

- [ ] **Step 5: Run the full database_ui test suite**

Run: `python -m pytest database_ui/tests -v && python -m database_ui.test_auth_public_static`
Expected: all pass (new tests + the standalone auth regression still green)

- [ ] **Step 6: Commit**

```bash
git add database_ui/routes/database.py database_ui/tests/test_export_routes.py
git commit -m "feat(database_ui): add /api/export/filters and /api/export.csv routes"
```

---

### Task 4: Frontend — Download button, modal, and picker

**Files:**
- Modify: `database_ui/templates/index.html`
- Create: `database_ui/static/js/download.js`
- Modify: `database_ui/static/css/database.css`

**Interfaces:**
- Consumes: `GET /api/export/filters`, `GET /api/export.csv`. Reuses chat.css modal classes (`.modal-overlay`, `.modal-card`, `.modal-title`, `.modal-body`, `.modal-actions`, `.modal-skip`, `.modal-submit`, `.modal-error`) already served at `/ui-core/css/chat.css` and used by `login.html`.
- Produces: a self-contained IIFE that opens/closes the modal and navigates to the CSV URL. No exports.

- [ ] **Step 1: Add the button + modal markup to `index.html`**

Inside `.sidebar-inner`, immediately after the `</div>` that closes `.sidebar-header` (before `<div class="sidebar-empty" ...>`), add:

```html
            <button type="button" class="sidebar-download" id="download-open" title="Download conversation data as CSV">
                <svg class="sidebar-download-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                    <polyline points="7 10 12 15 17 10"/>
                    <line x1="12" y1="15" x2="12" y2="3"/>
                </svg>
                <span>Download data</span>
            </button>
```

Immediately after the `</div>` that closes `.layout` (before the `<!-- Markdown rendering ... -->` comment), add the modal:

```html
    <div class="modal-overlay" id="download-modal" role="dialog" aria-modal="true"
         aria-labelledby="download-modal-title" hidden>
        <div class="modal-card download-card">
            <h2 id="download-modal-title" class="modal-title">Download data</h2>
            <p class="modal-body">Select courses and assignments to export as CSV (one row per message).</p>
            <div class="download-fields" id="download-fields"></div>
            <div class="modal-error" id="download-error" role="alert" hidden></div>
            <div class="modal-actions download-actions">
                <button type="button" id="download-cancel" class="modal-skip">Cancel</button>
                <button type="button" id="download-submit" class="modal-submit">Download CSV</button>
            </div>
        </div>
    </div>
```

Add the script include after the `database.js` line:

```html
    <script src="{{ url_for('static', filename='js/download.js') }}" defer></script>
```

- [ ] **Step 2: Write `database_ui/static/js/download.js`**

```javascript
"use strict";
// database_ui — "Download data" modal. Fetches the course/assignment options,
// lets the reviewer multi-select, then navigates to /api/export.csv to download.
(function () {
  const openBtn = document.getElementById("download-open");
  const modal = document.getElementById("download-modal");
  const fields = document.getElementById("download-fields");
  const errorBox = document.getElementById("download-error");
  const cancelBtn = document.getElementById("download-cancel");
  const submitBtn = document.getElementById("download-submit");
  if (!openBtn || !modal) return;

  function showError(msg) {
    errorBox.textContent = msg;
    errorBox.hidden = false;
  }
  function clearError() {
    errorBox.hidden = true;
    errorBox.textContent = "";
  }
  function closeModal() {
    modal.hidden = true;
  }

  // Build one course block: a course checkbox (checked) followed by its
  // assignment checkboxes (all checked). Unchecking the course disables its
  // whole assignment group so those pairs drop out of the selection.
  function renderCourse(course) {
    const block = document.createElement("div");
    block.className = "download-course";

    const head = document.createElement("label");
    head.className = "download-course-head";
    const courseCb = document.createElement("input");
    courseCb.type = "checkbox";
    courseCb.checked = true;
    courseCb.className = "download-course-cb";
    courseCb.dataset.course = course.course;
    const courseName = document.createElement("span");
    courseName.textContent = course.course_name || course.course;
    head.appendChild(courseCb);
    head.appendChild(courseName);
    block.appendChild(head);

    const group = document.createElement("div");
    group.className = "download-assignments";
    for (const a of course.assignments) {
      const row = document.createElement("label");
      row.className = "download-assignment";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = true;
      cb.className = "download-assignment-cb";
      cb.dataset.course = course.course;
      cb.dataset.exercise = a.exercise_number;
      const kind = a.exercise_kind === "practice" ? "Practice" : "Exercise";
      const label = document.createElement("span");
      label.textContent = kind + " " + a.exercise_number;
      row.appendChild(cb);
      row.appendChild(label);
      group.appendChild(row);
    }
    block.appendChild(group);

    // Toggling the course enables/disables (and visually dims) its assignments.
    courseCb.addEventListener("change", () => {
      group.classList.toggle("is-disabled", !courseCb.checked);
      for (const cb of group.querySelectorAll(".download-assignment-cb")) {
        cb.disabled = !courseCb.checked;
      }
    });
    return block;
  }

  function renderCourses(courses) {
    fields.innerHTML = "";
    if (!courses || courses.length === 0) {
      fields.textContent = "No data to export yet.";
      return;
    }
    for (const c of courses) fields.appendChild(renderCourse(c));
  }

  // Collect selected (course, exercise) pairs as "course::exercise" strings,
  // skipping assignments whose course is unchecked (their boxes are disabled).
  function selectedPairs() {
    const pairs = [];
    for (const cb of fields.querySelectorAll(".download-assignment-cb")) {
      if (cb.checked && !cb.disabled) {
        pairs.push(cb.dataset.course + "::" + cb.dataset.exercise);
      }
    }
    return pairs;
  }

  async function openModal() {
    clearError();
    fields.textContent = "Loading…";
    modal.hidden = false;
    try {
      const r = await fetch("/api/export/filters");
      if (!r.ok) {
        let msg = "Could not load export options";
        try {
          const body = await r.json();
          if (body && body.message) msg = body.message;
        } catch (_) {}
        fields.textContent = "";
        showError(msg);
        return;
      }
      const data = await r.json();
      renderCourses(data.courses);
    } catch (e) {
      fields.textContent = "";
      showError("Could not load export options");
    }
  }

  function submit() {
    const pairs = selectedPairs();
    if (pairs.length === 0) {
      showError("Select at least one assignment to download.");
      return;
    }
    const qs = pairs.map((p) => "assignment=" + encodeURIComponent(p)).join("&");
    // Plain navigation: the browser handles the file download from the
    // attachment response, then we close the modal.
    window.location = "/api/export.csv?" + qs;
    closeModal();
  }

  openBtn.addEventListener("click", openModal);
  cancelBtn.addEventListener("click", closeModal);
  submitBtn.addEventListener("click", submit);
  // Click on the dark backdrop (outside the card) closes the modal.
  modal.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });
})();
```

- [ ] **Step 3: Add styles to `database.css`**

Append:

```css
/* --- Download data button + modal ---------------------------------------- */
/* Sidebar action button under the header — full-width, accent-outlined, with a
   download glyph + label. Sits above the conversation list. */
.sidebar-download {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  width: 100%;
  margin: 0 0 0.5rem;
  padding: 0.45rem 0.6rem;
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--accent);
  background: transparent;
  border: 1px solid var(--accent);
  border-radius: 6px;
  cursor: pointer;
}
.sidebar-download:hover {
  background: #e3eff5;
}
.sidebar-download-icon {
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
}

/* Export picker: a scrollable list of course blocks, each with its assignment
   checkboxes. Reuses chat.css's .modal-overlay/.modal-card for the shell. */
.download-fields {
  max-height: 50vh;
  overflow-y: auto;
  margin: 0.5rem 0;
  text-align: left;
}
.download-course {
  margin-bottom: 0.6rem;
}
.download-course-head {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-weight: 600;
  cursor: pointer;
}
.download-assignments {
  margin: 0.25rem 0 0 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.download-assignments.is-disabled {
  opacity: 0.4;
}
.download-assignment {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.85rem;
  cursor: pointer;
}
.download-actions {
  display: flex;
  justify-content: space-between;
  gap: 0.5rem;
}
```

- [ ] **Step 4: Manually verify the flow against a seeded local DB**

Create a throwaway seeded SQLite DB and run the app against it:

```bash
python - <<'PY'
import os, uuid
from datetime import datetime, timezone
os.environ["DATABASE_UI_DATABASE_URL"] = "sqlite:///./_manual_export.db"
from database_ui.db.models import Base, Conversation, Message
from database_ui.db.session import engine, SessionLocal
Base.metadata.create_all(engine)
s = SessionLocal()
c = Conversation(id=uuid.uuid4(), session_id="s", username="a@mit.edu",
    course="supply_chain_design", exercise_number="1", exercise_kind="exercise",
    tutor_prompt="p", started_at=datetime.now(timezone.utc),
    last_active_at=datetime.now(timezone.utc))
s.add(c); s.flush()
s.add(Message(conversation_id=c.id, turn=1, role="student", content="hi", rating=0))
s.add(Message(conversation_id=c.id, turn=1, role="tutor", content="hello", rating=1,
    cost_usd=0.01, usage_json='{"model":"gpt-5.4"}'))
s.commit(); s.close()
print("seeded ./_manual_export.db")
PY

DATABASE_UI_DATABASE_URL="sqlite:///./_manual_export.db" python -m database_ui
```

Then in a browser at `http://127.0.0.1:5003`:
1. Confirm the **Download data** button shows under the sidebar header.
2. Click it — the modal opens listing "MIT CTL.SC2x Supply Chain Design" with "Exercise 1" checked.
3. Uncheck the course — its assignment dims/disables.
4. Re-check, click **Download CSV** — a file `asktim-export-2-msgs.csv` downloads.
5. Open the CSV — header row + 2 message rows, opens cleanly in Excel (BOM), `usage_json`/`retrieved_context` columns present.

Stop the server (Ctrl+C) and delete the scratch DB:

```bash
rm -f ./_manual_export.db
```

Expected: all five checks pass.

- [ ] **Step 5: Commit**

```bash
git add database_ui/templates/index.html database_ui/static/js/download.js database_ui/static/css/database.css
git commit -m "feat(database_ui): add Download data button, picker modal, and styles"
```

---

### Task 5: Documentation

**Files:**
- Modify: `database_ui/README.md`

**Interfaces:** none (docs only).

- [ ] **Step 1: Document the export endpoints in the README's Endpoints table**

In `database_ui/README.md`, add two rows to the `## Endpoints` table (after the `/api/image/<int>` row):

```markdown
| `GET /api/export/filters` | list courses + their assignments for the download picker |
| `GET /api/export.csv?assignment=<course>::<exercise>&…` | download selected conversations as a one-row-per-message CSV |
```

- [ ] **Step 2: Add a short feature note**

Under the top-of-file description (after the paragraph ending "…exercise header with the conversation's running total cost appended."), add:

```markdown

A **Download data** button in the sidebar opens a picker to multi-select courses
and assignments and download the matching conversations as a single CSV (one row
per message: content, pedagogical reasoning, rating, model, cost, raw
`usage_json` / `retrieved_context`, and an image count). Read-only like the rest
of the app — the export is pure `SELECT`.
```

- [ ] **Step 3: Commit**

```bash
git add database_ui/README.md
git commit -m "docs(database_ui): document the Download data CSV export"
```

---

## Self-Review

**Spec coverage:**
- Download button mirroring "Edit context" → Task 4 (button + modal). ✓
- Multi-select courses → Task 4 (course checkboxes). ✓
- Multi-select assignments, scoped/grouped/all-on → Task 4 (`renderCourse`, default checked, course toggle disables group). ✓
- One row per message → Task 2 (`iter_export_rows`). ✓
- CSV, UTF-8 + BOM, attachment → Task 3 (route). ✓
- Full column set incl. `pedagogical_reasoning`, raw `retrieved_context`, `usage_json`, `image_count` → Tasks 2–3 (`EXPORT_COLUMNS`, `_export_row`). ✓
- `/api/export/filters` + `/api/export.csv` endpoints → Task 3. ✓
- Scoped `course::exercise` pair identity → Tasks 3 (`_parse_assignment_pairs`) + 2 (pair filter). ✓
- Schema-drift 503 / empty-selection 400 / no-match header-only → Task 3 (+ tests). ✓
- Read-only, no deps, no schema change → honored throughout (stdlib `csv`, SELECT-only). ✓
- Testing (service + route) → Tasks 1–3. ✓

**Placeholder scan:** No TBD/TODO; every code step contains full code. Manual-verification step (Task 4 Step 4) is concrete with a runnable seed script.

**Type consistency:** `EXPORT_COLUMNS` defined in Task 1, consumed in Tasks 2 (`_export_row` keys) and 3 (`DictWriter` fieldnames). `iter_export_rows(db, pairs: set[tuple[str,str]])` produced in Task 2, consumed in Task 3. `_parse_assignment_pairs` returns the same `set[tuple[str,str]]` shape. `list_export_filters` shape defined in Task 1, consumed by the JS `renderCourses` in Task 4 (`course`, `course_name`, `assignments[].exercise_number`, `.exercise_kind`). Consistent.
