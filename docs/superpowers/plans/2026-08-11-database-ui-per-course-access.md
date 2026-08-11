# database_ui Per-Course Access Scoping — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give course staff their own passwords in `database_ui`, each scoped so a password only sees its own course(s)' conversations, exports, images, and files; keep one all-access master password.

**Architecture:** A new env var `DATABASE_UI_COURSE_PASSWORDS` (JSON list of `{password, courses}`) is parsed into config. On login, the submitted password resolves to a *Scope* (all-access, or a fixed list of course keys) stored in the Flask session. Every read path (`auth.allowed_courses()`) reads that scope back and filters queries by `Conversation.course`; by-ID endpoints (conversation / image / file) return 404 when the row's course is out of scope. No schema changes — the app stays read-only.

**Tech Stack:** Python 3, Flask, SQLAlchemy 2.0 (`select()` style), stdlib `json`/`hmac`, pytest.

## Global Constraints

- **Read-only, always.** No inserts/updates/migrations. Changes are auth checks and `SELECT` filters only. (`database_ui/README.md`)
- **No new dependencies.** Use stdlib `json` and `hmac` only.
- **Every module starts with** `from __future__ import annotations`.
- **Backward compatible:** only `DATABASE_UI_PASSWORD` set → single all-access password (today's behavior). Neither password var set → open local-dev mode (all-access).
- **Fail-safe config:** malformed/empty `DATABASE_UI_COURSE_PASSWORDS` grants **no** course access — never all-access.
- **Filter convention:** service functions take `courses: list[str] | None`; `None` means "no filter" (master/dev), preserving existing callers and tests. An empty list means "no access" → matches nothing.
- **Commits:** conventional-commit format (`type(scope): subject`). Do **not** add a `Co-Authored-By: Claude` trailer.
- **Run tests from repo root** (`d:\asktim_llm_tutor_project`) with the venv active: `pytest database_ui/ -v`.

---

## File Structure

- `database_ui/config.py` — **modify**: add `parse_course_passwords()` + `course_passwords` field on `Config`.
- `database_ui/run_app.py` — **modify**: surface `course_passwords` into `app.config`.
- `database_ui/auth.py` — **modify**: add `Scope`, `resolve_scope()`, scope-aware `mark_authed()`, `allowed_courses()`; make `password_required()` also count course passwords. Remove `check_password()`.
- `database_ui/routes/database.py` — **modify**: login uses `resolve_scope`; index passes a scope label; every data route filters by `allowed_courses()`.
- `database_ui/services/conversations.py` — **modify**: add `courses` filter to list/export/image/file queries.
- `database_ui/templates/index.html` — **modify**: render the scope label in the sidebar header.
- `database_ui/tests/test_config_course_passwords.py` — **create**: config parsing unit tests.
- `database_ui/tests/test_auth_scope.py` — **create**: `resolve_scope` / `allowed_courses` unit tests.
- `database_ui/tests/test_scoping.py` — **create**: end-to-end scoped-vs-master route tests (login, list, view, export, image, file).

---

### Task 1: Parse the course-password env var into config

**Files:**
- Modify: `database_ui/config.py`
- Modify: `database_ui/run_app.py`
- Test: `database_ui/tests/test_config_course_passwords.py` (create)

**Interfaces:**
- Produces: `parse_course_passwords(raw: str | None) -> dict[str, tuple[str, ...]]` (maps password → course keys; `{}` on any problem). `Config.course_passwords: dict[str, tuple[str, ...]]`.

- [ ] **Step 1: Write the failing test**

Create `database_ui/tests/test_config_course_passwords.py`:

```python
"""Unit tests for parsing DATABASE_UI_COURSE_PASSWORDS."""

from __future__ import annotations

from database_ui.config import parse_course_passwords


def test_parse_valid_entries():
    raw = '[{"password": "p1", "courses": ["a", "b"]}, {"password": "p2", "courses": ["c"]}]'
    assert parse_course_passwords(raw) == {"p1": ("a", "b"), "p2": ("c",)}


def test_none_and_empty_yield_empty_map():
    assert parse_course_passwords(None) == {}
    assert parse_course_passwords("") == {}
    assert parse_course_passwords("   ") == {}


def test_malformed_json_fails_safe_to_empty():
    assert parse_course_passwords("not json") == {}
    assert parse_course_passwords('{"password": "p"}') == {}  # object, not a list


def test_bad_entries_are_skipped():
    raw = (
        '[{"password": "", "courses": ["a"]},'          # empty password -> skip
        ' {"courses": ["b"]},'                           # no password -> skip
        ' {"password": "nostr", "courses": []},'         # no courses -> skip
        ' {"password": "ok", "courses": ["c", "", "d"]}]'  # empty course dropped
    )
    assert parse_course_passwords(raw) == {"ok": ("c", "d")}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest database_ui/tests/test_config_course_passwords.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_course_passwords'`

- [ ] **Step 3: Add the parser and config field**

In `database_ui/config.py`, add `import json` near the top (after `import os`), add the field to the dataclass, and add the parser + wiring.

Add to the `Config` dataclass (after `cookie_max_age_seconds`):

```python
    course_passwords: dict[str, tuple[str, ...]]
```

Add this function above `load_config`:

```python
def parse_course_passwords(raw: str | None) -> dict[str, tuple[str, ...]]:
    """Parse DATABASE_UI_COURSE_PASSWORDS into a ``{password: (course, ...)}`` map.

    The env value is a JSON list of ``{"password": str, "courses": [str, ...]}``
    entries. Anything malformed fails safe to an **empty** map (no course access
    granted) rather than raising — a bad config must never widen access. Entries
    missing a non-empty password or with no non-empty course keys are skipped;
    empty course strings within an entry are dropped.
    """
    if not raw or not raw.strip():
        return {}
    try:
        entries = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(entries, list):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        password = entry.get("password")
        courses = entry.get("courses")
        if not isinstance(password, str) or not password:
            continue
        if not isinstance(courses, list):
            continue
        keys = tuple(c for c in courses if isinstance(c, str) and c)
        if not keys:
            continue
        result[password] = keys
    return result
```

In `load_config`, after the `password = ...` line, add:

```python
    # Per-course passwords: {password: (course_key, ...)}. Empty/malformed -> {}
    # (no course access granted; the master password still works).
    course_passwords = parse_course_passwords(
        os.environ.get("DATABASE_UI_COURSE_PASSWORDS")
    )
```

And add `course_passwords=course_passwords,` to the `return Config(...)` call.

- [ ] **Step 4: Surface it into the app config**

In `database_ui/run_app.py`, after the `app.config["DATABASE_UI_PASSWORD"] = config.password` line, add:

```python
    # {password: (course_key, ...)} for scoped logins; {} => only the master
    # password (or open dev) is active. Read by the auth gate.
    app.config["DATABASE_UI_COURSE_PASSWORDS"] = config.course_passwords
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest database_ui/tests/test_config_course_passwords.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add database_ui/config.py database_ui/run_app.py database_ui/tests/test_config_course_passwords.py
git commit -m "feat(database_ui): parse per-course password config"
```

---

### Task 2: Resolve a password to a Scope; store/read it on the session

**Files:**
- Modify: `database_ui/auth.py`
- Test: `database_ui/tests/test_auth_scope.py` (create)

**Interfaces:**
- Consumes: `app.config["DATABASE_UI_COURSE_PASSWORDS"]` (from Task 1), `app.config["DATABASE_UI_PASSWORD"]`.
- Produces:
  - `Scope` dataclass: `Scope(all_access: bool, courses: tuple[str, ...])`.
  - `resolve_scope(candidate: str) -> Scope | None` — master → `Scope(True, ())`; a course password → `Scope(False, (...))`; no match → `None`.
  - `mark_authed(scope: Scope) -> None` — stores the scope in the session.
  - `allowed_courses() -> list[str] | None` — `None` = no filter (master/dev); a list = restrict to those course keys.
  - `password_required() -> bool` now true if **either** password var is configured.

- [ ] **Step 1: Write the failing test**

Create `database_ui/tests/test_auth_scope.py`:

```python
"""Unit tests for scope resolution and session read-back in auth.py."""

from __future__ import annotations

from database_ui.auth import Scope, allowed_courses, mark_authed, resolve_scope
from database_ui.run_app import create_app


def _app(master=None, course_passwords=None):
    app = create_app()
    app.config["DATABASE_UI_PASSWORD"] = master
    app.config["DATABASE_UI_COURSE_PASSWORDS"] = course_passwords or {}
    return app


def test_master_password_resolves_to_all_access():
    app = _app(master="master", course_passwords={"cp": ("supply_chain_design",)})
    with app.test_request_context():
        scope = resolve_scope("master")
        assert scope == Scope(all_access=True, courses=())


def test_course_password_resolves_to_its_courses():
    app = _app(master="master", course_passwords={"cp": ("supply_chain_design",)})
    with app.test_request_context():
        assert resolve_scope("cp") == Scope(all_access=False, courses=("supply_chain_design",))


def test_unknown_password_resolves_to_none():
    app = _app(master="master", course_passwords={"cp": ("x",)})
    with app.test_request_context():
        assert resolve_scope("nope") is None


def test_allowed_courses_reflects_stored_scope():
    app = _app(master="master", course_passwords={"cp": ("supply_chain_design",)})
    with app.test_request_context():
        mark_authed(Scope(all_access=False, courses=("supply_chain_design",)))
        assert allowed_courses() == ["supply_chain_design"]
        mark_authed(Scope(all_access=True, courses=()))
        assert allowed_courses() is None


def test_allowed_courses_is_none_when_no_password_configured():
    app = _app(master=None, course_passwords={})  # open local-dev mode
    with app.test_request_context():
        assert allowed_courses() is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest database_ui/tests/test_auth_scope.py -v`
Expected: FAIL with `ImportError: cannot import name 'Scope'`

- [ ] **Step 3: Implement Scope, resolution, and session read-back**

Rewrite `database_ui/auth.py` to this (keeps `is_authed`, the guard, and public endpoints; replaces `check_password` with scope logic):

```python
"""Password gate for database_ui, with optional per-course scoping.

The review tool exposes every student's conversations and uploaded files, so it
must not be open. A submitted password resolves to a *Scope*:

- the master ``DATABASE_UI_PASSWORD`` -> all-access (sees every course), or
- a per-course password (``DATABASE_UI_COURSE_PASSWORDS``) -> only its courses.

The resolved scope is stored in the signed Flask session cookie. If neither is
configured (local dev only), the gate is open and every request is all-access.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass

from flask import Flask, current_app, redirect, request, session, url_for

_SESSION_KEY = "database_authed"
_SESSION_ALL_ACCESS = "all_access"
_SESSION_COURSES = "allowed_courses"

_PUBLIC_ENDPOINTS = {
    "database.login",
    "database.login_submit",
    "health",
    "static",
    "ui_core.static",
}


@dataclass(frozen=True)
class Scope:
    """What a logged-in session may see.

    ``all_access`` -> every course (master password or open dev). Otherwise
    ``courses`` lists the curriculum keys this session is restricted to.
    """

    all_access: bool
    courses: tuple[str, ...]


def password_required() -> bool:
    """True if any password is configured (i.e. the gate is active)."""
    cfg = current_app.config
    return bool(cfg.get("DATABASE_UI_PASSWORD") or cfg.get("DATABASE_UI_COURSE_PASSWORDS"))


def is_authed() -> bool:
    """True if the current session may view the tool."""
    if not password_required():
        return True  # no password configured -> open (local dev)
    return bool(session.get(_SESSION_KEY))


def resolve_scope(candidate: str) -> Scope | None:
    """Resolve a submitted password to a :class:`Scope`, or ``None`` if no match.

    The master password wins and grants all-access; otherwise the candidate is
    matched against the per-course map. Comparisons are constant-time.
    """
    master = current_app.config.get("DATABASE_UI_PASSWORD")
    if master and hmac.compare_digest(candidate, master):
        return Scope(all_access=True, courses=())
    course_passwords: dict[str, tuple[str, ...]] = (
        current_app.config.get("DATABASE_UI_COURSE_PASSWORDS") or {}
    )
    for password, courses in course_passwords.items():
        if hmac.compare_digest(candidate, password):
            return Scope(all_access=False, courses=tuple(courses))
    return None


def allowed_courses() -> list[str] | None:
    """Course keys the current session is restricted to, or ``None`` for no filter.

    ``None`` means all-access (master password, or open local-dev mode). A list
    means restrict queries to exactly those course keys.
    """
    if not password_required():
        return None
    if session.get(_SESSION_ALL_ACCESS):
        return None
    return list(session.get(_SESSION_COURSES, []))


def mark_authed(scope: Scope) -> None:
    """Mark the session authenticated for *scope* and make the cookie permanent."""
    session[_SESSION_KEY] = True
    session[_SESSION_ALL_ACCESS] = scope.all_access
    session[_SESSION_COURSES] = list(scope.courses)
    session.permanent = True


def clear_auth() -> None:
    """Clear all auth/scope state from the current session (log out)."""
    session.pop(_SESSION_KEY, None)
    session.pop(_SESSION_ALL_ACCESS, None)
    session.pop(_SESSION_COURSES, None)


def init_auth(app: Flask) -> None:
    """Register the before-request guard that protects every non-public route."""

    @app.before_request
    def _require_auth():
        """Redirect to the login page unless the endpoint is public or authed."""
        if request.endpoint in _PUBLIC_ENDPOINTS:
            return None
        if is_authed():
            return None
        return redirect(url_for("database.login"))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest database_ui/tests/test_auth_scope.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add database_ui/auth.py database_ui/tests/test_auth_scope.py
git commit -m "feat(database_ui): resolve passwords to session scopes"
```

---

### Task 3: Wire login to scope resolution and show the active scope

**Files:**
- Modify: `database_ui/routes/database.py` (imports, `login_submit`, `index`)
- Modify: `database_ui/templates/index.html`
- Test: `database_ui/tests/test_scoping.py` (create — login cases only in this task)

**Interfaces:**
- Consumes: `resolve_scope`, `mark_authed`, `allowed_courses` (Task 2), `course_display_name` (existing).
- Produces: a `scope_label` template variable on the index page; scoped/rejected login behavior via `/login`.

- [ ] **Step 1: Write the failing test**

Create `database_ui/tests/test_scoping.py`:

```python
"""End-to-end scope enforcement across login and every read path."""

from __future__ import annotations

import pytest

from database_ui.conftest import seed
from database_ui.db.models import UploadedFile, UploadedImage
from database_ui.db.session import SessionLocal
from database_ui.run_app import create_app

MASTER = "master-secret"
SC_PW = "supply-secret"      # scoped to supply_chain_design
MOL_PW = "meaning-secret"    # scoped to meaning_of_life


def _app():
    app = create_app()
    app.config["DATABASE_UI_PASSWORD"] = MASTER
    app.config["DATABASE_UI_COURSE_PASSWORDS"] = {
        SC_PW: ("supply_chain_design",),
        MOL_PW: ("meaning_of_life",),
    }
    return app


def _login(app, password):
    client = app.test_client()
    client.post("/login", data={"password": password})
    return client


@pytest.fixture()
def seeded():
    from database_ui.db.models import Conversation, Message
    session = SessionLocal()
    session.query(UploadedImage).delete()
    session.query(UploadedFile).delete()
    session.query(Message).delete()
    session.query(Conversation).delete()
    session.commit()
    ids = seed(session)
    # seed() attaches one image and one file to the supply_chain student message.
    ids["image_id"] = session.query(UploadedImage.id).scalar()
    ids["file_id"] = session.query(UploadedFile.id).scalar()
    session.close()
    return ids


def test_scoped_password_logs_in():
    resp = _app().test_client().post("/login", data={"password": SC_PW})
    assert resp.status_code == 302


def test_unknown_password_is_rejected():
    resp = _app().test_client().post("/login", data={"password": "nope"})
    assert resp.status_code == 401


def test_index_shows_scope_label():
    body = _login(_app(), SC_PW).get("/").get_data(as_text=True)
    assert "MIT CTL.SC2x Supply Chain Design" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest database_ui/tests/test_scoping.py -v`
Expected: FAIL — `test_index_shows_scope_label` fails (label not rendered); the login tests may already pass or error on the import path. Fix in Step 3.

- [ ] **Step 3: Update the login and index routes**

In `database_ui/routes/database.py`, change the auth import line:

```python
from database_ui.auth import allowed_courses, clear_auth, mark_authed, resolve_scope
```

Replace the body of `login_submit` (keep the decorator and docstring):

```python
    candidate = request.form.get("password", "")
    scope = resolve_scope(candidate)
    if scope is not None:
        mark_authed(scope)
        return redirect(url_for("database.index"))
    return (
        render_template(
            "login.html",
            title=current_app.config["DATABASE_UI_TITLE"],
            accent=current_app.config["DATABASE_UI_ACCENT"],
            error="Wrong password, try again",
        ),
        401,
    )
```

Add this helper just above the `index` route:

```python
def _scope_label() -> str:
    """Human-readable label for the current session's scope (for the header)."""
    courses = allowed_courses()
    if courses is None:
        return "All courses"
    return ", ".join(course_display_name(c) for c in courses)
```

Add the import it needs (top of file, with the other `database_ui` imports):

```python
from database_ui.courses import course_display_name
```

Pass the label into `index`'s `render_template`:

```python
    return render_template(
        "index.html",
        title=current_app.config["DATABASE_UI_TITLE"],
        accent=current_app.config["DATABASE_UI_ACCENT"],
        scope_label=_scope_label(),
    )
```

- [ ] **Step 4: Render the label in the template**

In `database_ui/templates/index.html`, the sidebar header currently reads:

```html
                <h2 class="sidebar-title">AskTIM <span class="beta-tag">· Database Beta+</span></h2>
```

Add a scope line right after it:

```html
                <h2 class="sidebar-title">AskTIM <span class="beta-tag">· Database Beta+</span></h2>
                <p class="sidebar-scope">Viewing: {{ scope_label }}</p>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest database_ui/tests/test_scoping.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
git add database_ui/routes/database.py database_ui/templates/index.html database_ui/tests/test_scoping.py
git commit -m "feat(database_ui): scope login and show active scope in header"
```

---

### Task 4: Scope the conversation list and single-conversation view

**Files:**
- Modify: `database_ui/services/conversations.py` (`list_all_conversations`)
- Modify: `database_ui/routes/database.py` (`api_conversations`, `api_conversation`)
- Test: `database_ui/tests/test_scoping.py` (add to the file from Task 3)

**Interfaces:**
- Consumes: `allowed_courses()` (Task 2), the `seeded` fixture + `_app`/`_login` helpers (Task 3).
- Produces: `list_all_conversations(..., courses: list[str] | None = None)` — filters by `Conversation.course` when `courses` is not `None`.

- [ ] **Step 1: Write the failing test**

Append to `database_ui/tests/test_scoping.py`:

```python
def test_scoped_list_shows_only_own_course(seeded):
    client = _login(_app(), SC_PW)
    data = client.get("/api/conversations").get_json()
    courses = {c["course"] for c in data["conversations"]}
    assert courses == {"supply_chain_design"}


def test_master_list_shows_all_courses(seeded):
    client = _login(_app(), MASTER)
    data = client.get("/api/conversations").get_json()
    courses = {c["course"] for c in data["conversations"]}
    assert courses == {"supply_chain_design", "meaning_of_life"}


def test_scoped_view_blocks_other_course_conversation(seeded):
    client = _login(_app(), SC_PW)
    assert client.get(f"/api/conversation/{seeded['mol_id']}").status_code == 404
    assert client.get(f"/api/conversation/{seeded['sc_id']}").status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest database_ui/tests/test_scoping.py -v -k "list or view"`
Expected: FAIL — scoped list returns both courses; the other-course conversation returns 200.

- [ ] **Step 3: Add the `courses` filter to the list query**

In `database_ui/services/conversations.py`, change `list_all_conversations`'s signature and statement:

```python
def list_all_conversations(
    db: Session,
    *,
    sort: str = "date",
    limit: int | None = None,
    offset: int = 0,
    courses: list[str] | None = None,
) -> list[dict]:
```

Just after `stmt = select(Conversation).order_by(*order)`, insert:

```python
    if courses is not None:
        stmt = stmt.where(Conversation.course.in_(courses))
```

(Update the docstring's last paragraph to note: "``courses`` restricts the list to those course keys; ``None`` returns every course.")

- [ ] **Step 4: Enforce scope in the routes**

In `database_ui/routes/database.py`, in `api_conversations`, change the service call to pass the scope:

```python
        conversations = svc.list_all_conversations(
            g.db, sort=sort, limit=limit, offset=offset, courses=allowed_courses()
        )
```

In `api_conversation`, after `convo = svc.get_conversation(g.db, convo_id)` and the existing `None` check, add the scope check:

```python
    convo = svc.get_conversation(g.db, convo_id)
    if convo is None:
        return jsonify({"error": "not_found"}), 404
    courses = allowed_courses()
    if courses is not None and convo.course not in courses:
        return jsonify({"error": "not_found"}), 404
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest database_ui/tests/test_scoping.py -v -k "list or view"`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the full existing suite for regressions**

Run: `pytest database_ui/ -v`
Expected: PASS (existing conversation/export tests still green — they call the service without `courses`, so behavior is unchanged).

- [ ] **Step 7: Commit**

```bash
git add database_ui/services/conversations.py database_ui/routes/database.py database_ui/tests/test_scoping.py
git commit -m "feat(database_ui): scope conversation list and view by course"
```

---

### Task 5: Scope the CSV export (filters and rows)

**Files:**
- Modify: `database_ui/services/conversations.py` (`list_export_filters`, `iter_export_rows`)
- Modify: `database_ui/routes/database.py` (`api_export_filters`, `api_export_csv`)
- Test: `database_ui/tests/test_scoping.py` (add to the same file)

**Interfaces:**
- Consumes: `allowed_courses()`, the `seeded`/`_app`/`_login` helpers.
- Produces: `list_export_filters(db, courses: list[str] | None = None)` and `iter_export_rows(db, pairs, courses: list[str] | None = None)` — both restrict to `courses` when not `None`.

- [ ] **Step 1: Write the failing test**

Append to `database_ui/tests/test_scoping.py`:

```python
def test_scoped_export_filters_show_only_own_course(seeded):
    client = _login(_app(), MOL_PW)
    data = client.get("/api/export/filters").get_json()
    assert [c["course"] for c in data["courses"]] == ["meaning_of_life"]


def test_scoped_export_rows_cannot_pull_other_course(seeded):
    # Scoped to meaning_of_life, request supply_chain_design's rows (which DO
    # exist) -> the scope filter drops them, leaving a header-only CSV.
    client = _login(_app(), MOL_PW)
    resp = client.get("/api/export.csv?assignment=supply_chain_design::1")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True).lstrip("\ufeff")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) == 1  # header only, no supply_chain rows


def test_master_export_rows_include_supply_chain(seeded):
    client = _login(_app(), MASTER)
    resp = client.get("/api/export.csv?assignment=supply_chain_design::1")
    body = resp.get_data(as_text=True).lstrip("\ufeff")
    lines = [ln for ln in body.splitlines() if ln.strip()]
    assert len(lines) >= 3  # header + 2 message rows
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest database_ui/tests/test_scoping.py -v -k export`
Expected: FAIL — scoped filters list both courses; scoped export returns supply_chain rows.

- [ ] **Step 3: Add the `courses` filter to the export queries**

In `database_ui/services/conversations.py`:

Change `list_export_filters` to accept and apply the filter:

```python
def list_export_filters(db: Session, courses: list[str] | None = None) -> list[dict]:
```

After the `stmt = select(...).distinct()` block, before executing, add:

```python
    if courses is not None:
        stmt = stmt.where(Conversation.course.in_(courses))
```

Change `iter_export_rows` to accept the filter and intersect the requested pairs:

```python
def iter_export_rows(db: Session, pairs: set[tuple[str, str]], courses: list[str] | None = None):
```

Right after the existing `if not pairs: return` guard, add:

```python
    if courses is not None:
        allowed = set(courses)
        pairs = {(course, ex) for course, ex in pairs if course in allowed}
        if not pairs:
            return
```

- [ ] **Step 4: Enforce scope in the export routes**

In `database_ui/routes/database.py`:

In `api_export_filters`, pass the scope:

```python
        courses = svc.list_export_filters(g.db, allowed_courses())
```

In `api_export_csv`, pass the scope into the row iterator:

```python
        rows = list(svc.iter_export_rows(g.db, pairs, allowed_courses()))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest database_ui/tests/test_scoping.py -v -k export`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the export regression suite**

Run: `pytest database_ui/tests/test_export_routes.py database_ui/tests/test_export_service.py -v`
Expected: PASS (existing export tests call without `courses`, so unchanged).

- [ ] **Step 7: Commit**

```bash
git add database_ui/services/conversations.py database_ui/routes/database.py database_ui/tests/test_scoping.py
git commit -m "feat(database_ui): scope CSV export filters and rows by course"
```

---

### Task 6: Scope the image and file byte endpoints

**Files:**
- Modify: `database_ui/services/conversations.py` (`get_image`, `get_file`)
- Modify: `database_ui/routes/database.py` (`api_image`, `api_file`)
- Test: `database_ui/tests/test_scoping.py` (add to the same file)

**Interfaces:**
- Consumes: `allowed_courses()`, `seeded` (provides `image_id`, `file_id`), models `Message`/`Conversation` (already imported in the service).
- Produces: `get_image(db, image_id, courses: list[str] | None = None)` and `get_file(db, file_id, courses: list[str] | None = None)` — return the row only if its owning conversation's course is in scope (or `courses is None`).

- [ ] **Step 1: Write the failing test**

Append to `database_ui/tests/test_scoping.py`:

```python
def test_scoped_user_cannot_fetch_other_course_image(seeded):
    # image belongs to supply_chain_design; a meaning_of_life user must get 404.
    client = _login(_app(), MOL_PW)
    assert client.get(f"/api/image/{seeded['image_id']}").status_code == 404


def test_scoped_user_can_fetch_own_course_image(seeded):
    client = _login(_app(), SC_PW)
    assert client.get(f"/api/image/{seeded['image_id']}").status_code == 200


def test_scoped_user_cannot_fetch_other_course_file(seeded):
    client = _login(_app(), MOL_PW)
    assert client.get(f"/api/file/{seeded['file_id']}").status_code == 404


def test_master_can_fetch_image_and_file(seeded):
    client = _login(_app(), MASTER)
    assert client.get(f"/api/image/{seeded['image_id']}").status_code == 200
    assert client.get(f"/api/file/{seeded['file_id']}").status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest database_ui/tests/test_scoping.py -v -k "image or file"`
Expected: FAIL — the meaning_of_life user gets 200 for the supply_chain image/file (no scope check yet).

- [ ] **Step 3: Add scope-aware lookups**

In `database_ui/services/conversations.py`, replace `get_image` and `get_file`:

```python
def get_image(
    db: Session, image_id: int, courses: list[str] | None = None
) -> UploadedImage | None:
    """Fetch one uploaded image by id, restricted to *courses* when not ``None``.

    ``courses is None`` -> review sees all (master/dev). Otherwise the image is
    returned only if its owning conversation's course is in scope; a
    cross-course id yields ``None`` (the route turns that into a 404).
    """
    if courses is None:
        return db.get(UploadedImage, image_id)
    stmt = (
        select(UploadedImage)
        .join(Message, UploadedImage.message_id == Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(UploadedImage.id == image_id, Conversation.course.in_(courses))
    )
    return db.execute(stmt).scalars().first()


def get_file(
    db: Session, file_id: int, courses: list[str] | None = None
) -> UploadedFile | None:
    """Fetch one uploaded non-image file by id, restricted to *courses* when set.

    Same scoping rule as :func:`get_image`: a cross-course id yields ``None``.
    """
    if courses is None:
        return db.get(UploadedFile, file_id)
    stmt = (
        select(UploadedFile)
        .join(Message, UploadedFile.message_id == Message.id)
        .join(Conversation, Message.conversation_id == Conversation.id)
        .where(UploadedFile.id == file_id, Conversation.course.in_(courses))
    )
    return db.execute(stmt).scalars().first()
```

- [ ] **Step 4: Pass the scope from the routes**

In `database_ui/routes/database.py`:

In `api_image`, change the lookup:

```python
    img = svc.get_image(g.db, image_id, allowed_courses())
```

In `api_file`, change the lookup:

```python
    row = svc.get_file(g.db, file_id, allowed_courses())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest database_ui/tests/test_scoping.py -v -k "image or file"`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full suite**

Run: `pytest database_ui/ -v`
Expected: PASS (all scoping tests + all existing tests green).

- [ ] **Step 7: Commit**

```bash
git add database_ui/services/conversations.py database_ui/routes/database.py database_ui/tests/test_scoping.py
git commit -m "feat(database_ui): scope image and file downloads by course"
```

---

## Self-Review

**Spec coverage:**
- Config via env var JSON list → Task 1. ✅
- Master + one-password-→-many-courses → Task 1 (map value is a tuple of keys) + Task 2 (`resolve_scope`). ✅
- Single password-box login, no course-list leak → Task 3 (login unchanged except resolution). ✅
- Scope everything — list/view → Task 4; export filters/rows → Task 5; image/file bytes → Task 6. ✅
- Cross-course by-ID → 404 → Tasks 4 (conversation) and 6 (image/file). ✅
- Fail-safe config → Task 1 (`parse_course_passwords` returns `{}`), plus `resolve_scope` returns `None` for non-matches. ✅
- Backward compatibility (only master / neither var) → Task 2 (`password_required`, `allowed_courses`) + Global Constraints; existing suites re-run in Tasks 4–6. ✅
- Read-only preserved → all changes are `SELECT` filters / auth; no writes. ✅
- Header scope signpost → Task 3. ✅

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code and test step is concrete. ✅

**Type consistency:** `Scope(all_access, courses)`, `resolve_scope() -> Scope | None`, `allowed_courses() -> list[str] | None`, and the `courses: list[str] | None` service parameter are used identically across Tasks 2–6. Routes always source the filter from `allowed_courses()`. The `seeded` fixture (Task 3) is extended with `image_id`/`file_id` and reused in Tasks 4–6. ✅
