# ui_core Phase 1 — DB session + cookies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scaffold the `ui_core` package and extract the two pure-infra web files — DB engine/session and cookie policy — into shared helpers, with each app reduced to a thin wrapper that keeps its public names.

**Architecture:** Shared helper functions in `ui_core` capture behavior that was hard-coded per app, exposed as explicit parameters. Each app's `db/session.py` and `cookies.py` become thin wrappers that call the shared helpers with their per-app values and re-export the same names (`engine`, `SessionLocal`, `get_session`, `SESSION_COOKIE_NAME`, `USERNAME_COOKIE_NAME`, `new_session_id`, `default_cookie_kwargs`), so no call sites change. Behavior-preserving.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x (`future=True`), Flask, `psycopg` (psycopg3). Repo test style is **standalone, no pytest**: a `main()` + `_check()` harness returning non-zero on failure, run via `python -m <module>`.

## Global Constraints

- **Behavior-preserving:** every app must behave exactly as before. The shared helpers reproduce each app's current behavior via parameters; nothing changes at call sites.
- **Public names preserved:** `main_ui.db.session` / `sandbox_ui.db.session` / `database_ui.db.session` must still expose `engine`, `SessionLocal`, `get_session`; `main_ui.cookies` / `sandbox_ui.cookies` must still expose `SESSION_COOKIE_NAME`, `USERNAME_COOKIE_NAME`, `new_session_id`, `default_cookie_kwargs`.
- **No schema / migration changes.** This phase does not touch models or Alembic.
- **No API keys / network.** All tasks are offline; tests use temp-file SQLite.
- **No `Co-Authored-By: Claude` trailer** in commits (repo convention).
- Per-app behavior knobs today: main_ui + sandbox_ui build engine with SQLite FK enforcement on connect, commit-on-success sessions. `database_ui` normalizes `postgres://`/`postgresql://` → `postgresql+psycopg://`, uses `pool_pre_ping=True`, no SQLite FK hook, and a read-only session (rolls back, never commits). `database_ui` has **no** `cookies.py`.

---

## File structure

- `ui_core/__init__.py` — CREATE (empty package marker).
- `ui_core/db/__init__.py` — CREATE (empty).
- `ui_core/db/session.py` — CREATE: `normalize_pg_url`, `build_engine`, `make_session_factory`, `session_scope`.
- `ui_core/db/test_session.py` — CREATE: standalone tests.
- `ui_core/cookies.py` — CREATE: shared cookie constants + policy.
- `ui_core/test_cookies.py` — CREATE: standalone tests.
- `main_ui/db/session.py` — REPLACE with thin wrapper.
- `sandbox_ui/db/session.py` — REPLACE with thin wrapper.
- `database_ui/db/session.py` — REPLACE with thin wrapper.
- `main_ui/cookies.py` — REPLACE with thin wrapper.
- `sandbox_ui/cookies.py` — REPLACE with thin wrapper.

---

### Task 1: Shared DB session helpers (`ui_core.db.session`)

**Files:**
- Create: `ui_core/__init__.py`, `ui_core/db/__init__.py`, `ui_core/db/session.py`
- Test: `ui_core/db/test_session.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `normalize_pg_url(url: str) -> str`
  - `build_engine(database_url: str, *, sqlite_fk: bool = False, pool_pre_ping: bool = False, normalize_pg: bool = False) -> sqlalchemy.engine.Engine`
  - `make_session_factory(engine) -> sqlalchemy.orm.sessionmaker`
  - `session_scope(session_factory, *, read_only: bool = False)` — a context manager yielding a `Session`; commits on success unless `read_only`, always rolls back+closes appropriately.

- [ ] **Step 1: Create the empty package markers**

Create `ui_core/__init__.py`:
```python
"""Shared web layer (Flask app factory, blueprints, db, cookies) for the UIs."""
```
Create `ui_core/db/__init__.py`:
```python
```

- [ ] **Step 2: Write the failing test**

Create `ui_core/db/test_session.py`:
```python
"""Standalone tests for ui_core.db.session (no pytest).

Run with:
    python -m ui_core.db.test_session
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy import Column, Integer, text
from sqlalchemy.orm import declarative_base

from ui_core.db.session import (
    normalize_pg_url,
    build_engine,
    make_session_factory,
    session_scope,
)

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def test_normalize_pg_url() -> None:
    _check("postgres:// -> psycopg", normalize_pg_url("postgres://u@h/db") == "postgresql+psycopg://u@h/db")
    _check("postgresql:// -> psycopg", normalize_pg_url("postgresql://u@h/db") == "postgresql+psycopg://u@h/db")
    _check("already explicit unchanged", normalize_pg_url("postgresql+psycopg://u@h/db") == "postgresql+psycopg://u@h/db")
    _check("sqlite unchanged", normalize_pg_url("sqlite:///x.db") == "sqlite:///x.db")


def test_build_engine_sqlite_fk_enforced() -> None:
    Base = declarative_base()

    class Parent(Base):
        __tablename__ = "parent"
        id = Column(Integer, primary_key=True)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        url = f"sqlite:///{Path(tmp) / 'fk.db'}"
        eng_on = build_engine(url, sqlite_fk=True)
        Base.metadata.create_all(eng_on)
        with eng_on.connect() as conn:
            fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
        eng_on.dispose()
        _check("sqlite_fk=True turns PRAGMA foreign_keys on", fk == 1, f"got {fk}")

        url2 = f"sqlite:///{Path(tmp) / 'nofk.db'}"
        eng_off = build_engine(url2, sqlite_fk=False)
        with eng_off.connect() as conn:
            fk_off = conn.execute(text("PRAGMA foreign_keys")).scalar()
        eng_off.dispose()
        _check("sqlite_fk=False leaves PRAGMA off", fk_off == 0, f"got {fk_off}")


def test_session_scope_commit_vs_readonly() -> None:
    Base = declarative_base()

    class Row(Base):
        __tablename__ = "row"
        id = Column(Integer, primary_key=True)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        url = f"sqlite:///{Path(tmp) / 'scope.db'}"
        engine = build_engine(url)
        Base.metadata.create_all(engine)
        factory = make_session_factory(engine)

        with session_scope(factory) as s:      # read_only=False -> commits
            s.add(Row(id=1))
        with session_scope(factory) as s:
            persisted = s.get(Row, 1) is not None
        _check("non-read-only scope commits", persisted)

        with session_scope(factory, read_only=True) as s:   # rolls back
            s.add(Row(id=2))
        with session_scope(factory) as s:
            rolled_back = s.get(Row, 2) is None
        _check("read_only scope rolls back", rolled_back)
        engine.dispose()


def main() -> int:
    for t in (test_normalize_pg_url, test_build_engine_sqlite_fk_enforced, test_session_scope_commit_vs_readonly):
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m ui_core.db.test_session`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui_core.db.session'` (module not created yet).

- [ ] **Step 4: Write the shared helpers**

Create `ui_core/db/session.py`:
```python
"""Shared SQLAlchemy engine + session helpers for the web apps.

Each app builds its engine and session factory from these helpers, passing the
behavior knobs that used to be hard-coded per app:

- ``sqlite_fk``: enable SQLite foreign-key enforcement on connect (main/sandbox).
- ``pool_pre_ping``: guard stale connections to a long-lived remote DB (database_ui).
- ``normalize_pg``: rewrite ``postgres://`` / ``postgresql://`` to
  ``postgresql+psycopg://`` so SQLAlchemy uses psycopg3 (database_ui; the live
  apps' entrypoints do the same for their own URLs).
- ``read_only``: ``session_scope`` rolls back instead of committing (database_ui).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def normalize_pg_url(url: str) -> str:
    """Make the Postgres driver explicit so SQLAlchemy doesn't reach for psycopg2."""
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url  # already explicit, or sqlite — leave as-is


def build_engine(
    database_url: str,
    *,
    sqlite_fk: bool = False,
    pool_pre_ping: bool = False,
    normalize_pg: bool = False,
) -> Engine:
    """Build a SQLAlchemy engine with the requested per-app behavior."""
    url = normalize_pg_url(database_url) if normalize_pg else database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    engine = create_engine(
        url, connect_args=connect_args, pool_pre_ping=pool_pre_ping, future=True
    )
    if sqlite_fk:
        @event.listens_for(engine, "connect")
        def _enable_sqlite_fk(dbapi_conn, _connection_record):
            """Enable foreign-key enforcement on SQLite connections."""
            if engine.dialect.name == "sqlite":
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    """Session factory with the shared settings used by every app."""
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(session_factory: sessionmaker, *, read_only: bool = False) -> Iterator[Session]:
    """Yield a Session. Commit on success unless *read_only*; roll back on error.

    read_only sessions never commit and always roll back on exit — the behavior
    database_ui relies on to guarantee it never writes.
    """
    session = session_factory()
    try:
        yield session
        if not read_only:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if read_only:
            session.rollback()
        session.close()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m ui_core.db.test_session`
Expected: PASS — `3 test functions`, `9 passed, 0 failed`.

- [ ] **Step 6: Commit**

```bash
git add ui_core/__init__.py ui_core/db/__init__.py ui_core/db/session.py ui_core/db/test_session.py
git commit -m "feat(ui_core): add shared DB engine/session helpers"
```

---

### Task 2: Rewire the three apps' `db/session.py` to thin wrappers

**Files:**
- Modify (replace whole file): `main_ui/db/session.py`, `sandbox_ui/db/session.py`, `database_ui/db/session.py`

**Interfaces:**
- Consumes: `ui_core.db.session.{build_engine, make_session_factory, session_scope}` (Task 1).
- Produces: each module still exposes `engine`, `SessionLocal`, `get_session` (unchanged names/behavior).

- [ ] **Step 1: Replace `main_ui/db/session.py`**

```python
"""SQLAlchemy engine + session factory for main_ui.

Thin wrapper over ui_core.db.session: SQLite FK enforcement on, commit-on-success
sessions. Public names (engine, SessionLocal, get_session) are unchanged.
"""

from __future__ import annotations

from ui_core.db.session import build_engine, make_session_factory, session_scope
from main_ui.config import load_config

engine = build_engine(load_config().database_url, sqlite_fk=True)
SessionLocal = make_session_factory(engine)


def get_session():
    """Yield a SQLAlchemy Session; commit on success, rollback on exception."""
    return session_scope(SessionLocal, read_only=False)
```

- [ ] **Step 2: Replace `sandbox_ui/db/session.py`**

```python
"""SQLAlchemy engine + session factory for sandbox_ui.

Thin wrapper over ui_core.db.session (same behavior as main_ui: SQLite FK on,
commit-on-success). Public names unchanged.
"""

from __future__ import annotations

from ui_core.db.session import build_engine, make_session_factory, session_scope
from sandbox_ui.config import load_config

engine = build_engine(load_config().database_url, sqlite_fk=True)
SessionLocal = make_session_factory(engine)


def get_session():
    """Yield a SQLAlchemy Session; commit on success, rollback on exception."""
    return session_scope(SessionLocal, read_only=False)
```

- [ ] **Step 3: Replace `database_ui/db/session.py`**

```python
"""SQLAlchemy engine + session factory for database_ui (read-only).

Thin wrapper over ui_core.db.session: normalizes Railway/Heroku postgres URLs to
psycopg3, uses pool_pre_ping for a long-lived remote DB, and a read-only session
that always rolls back (this app never writes). Public names unchanged.
"""

from __future__ import annotations

from ui_core.db.session import build_engine, make_session_factory, session_scope
from database_ui.config import load_config

engine = build_engine(
    load_config().database_url, pool_pre_ping=True, normalize_pg=True
)
SessionLocal = make_session_factory(engine)


def get_session():
    """Yield a read-only Session; always rolls back (this app never writes)."""
    return session_scope(SessionLocal, read_only=True)
```

- [ ] **Step 4: Verify all three import and keep their public surface**

Run:
```bash
python -c "import importlib; [importlib.import_module(m+'.db.session') for m in ('main_ui','sandbox_ui','database_ui')]; from main_ui.db.session import engine,SessionLocal,get_session; from database_ui.db.session import get_session as g; print('imports OK')"
```
Expected: prints `imports OK` (no ImportError; `create_engine` is lazy so no DB connection is made at import). If `load_config()` raises for a missing env var, set a dummy `DATABASE_URL=sqlite:///tmp.db` for the command and note it — do NOT change config in this phase.

- [ ] **Step 5: Verify read-only vs commit behavior end-to-end per app**

Run:
```bash
python - <<'PY'
import tempfile, os
from pathlib import Path
# Point every app's config at a throwaway sqlite DB via env, then exercise get_session.
tmp = Path(tempfile.mkdtemp()) / "verify.db"
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}"
from sqlalchemy import text
from main_ui.db.session import engine, get_session
with engine.begin() as conn:
    conn.execute(text("CREATE TABLE t (id INTEGER PRIMARY KEY)"))
with get_session() as s:
    s.execute(text("INSERT INTO t (id) VALUES (1)"))
with get_session() as s:
    committed = s.execute(text("SELECT COUNT(*) FROM t")).scalar()
print("main_ui commits:", committed == 1)
PY
```
Expected: prints `main_ui commits: True`. (The `ui_core` unit test already proves read-only rollback; this confirms the wrapper wiring.)

- [ ] **Step 6: Commit**

```bash
git add main_ui/db/session.py sandbox_ui/db/session.py database_ui/db/session.py
git commit -m "refactor(web): route app db/session through ui_core helpers"
```

---

### Task 3: Shared cookie policy (`ui_core.cookies`) + app wrappers

**Files:**
- Create: `ui_core/cookies.py`, `ui_core/test_cookies.py`
- Modify (replace whole file): `main_ui/cookies.py`, `sandbox_ui/cookies.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ui_core.cookies`: `SESSION_COOKIE_NAME`, `USERNAME_COOKIE_NAME`, `new_session_id() -> str`, `default_cookie_kwargs(*, secure: bool, max_age: int) -> dict`.
  - `main_ui.cookies` / `sandbox_ui.cookies` still expose `SESSION_COOKIE_NAME`, `USERNAME_COOKIE_NAME`, `new_session_id`, and a **no-arg** `default_cookie_kwargs()` (reads that app's config).

- [ ] **Step 1: Write the failing test**

Create `ui_core/test_cookies.py`:
```python
"""Standalone tests for ui_core.cookies (no pytest).

Run with:
    python -m ui_core.test_cookies
"""

from __future__ import annotations

import uuid

from ui_core.cookies import (
    SESSION_COOKIE_NAME,
    USERNAME_COOKIE_NAME,
    new_session_id,
    default_cookie_kwargs,
)

_PASSED = 0
_FAILED = 0


def _check(name: str, condition: bool, detail: str = "") -> None:
    global _PASSED, _FAILED
    if condition:
        _PASSED += 1
        print(f"  PASS  {name}")
    else:
        _FAILED += 1
        print(f"  FAIL  {name}  {detail}")


def test_constants_and_session_id() -> None:
    _check("session cookie name", SESSION_COOKIE_NAME == "tutor_session_id")
    _check("username cookie name", USERNAME_COOKIE_NAME == "tutor_username")
    sid = new_session_id()
    _check("new_session_id is a uuid4 string", str(uuid.UUID(sid)) == sid)


def test_default_cookie_kwargs() -> None:
    got = default_cookie_kwargs(secure=True, max_age=100)
    _check(
        "policy dict is exact",
        got == {"httponly": True, "samesite": "None", "secure": True, "max_age": 100, "path": "/", "partitioned": True},
        f"got {got}",
    )
    _check("secure passes through", default_cookie_kwargs(secure=False, max_age=1)["secure"] is False)


def main() -> int:
    for t in (test_constants_and_session_id, test_default_cookie_kwargs):
        print(t.__name__)
        t()
    print(f"\n{_PASSED} passed, {_FAILED} failed")
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m ui_core.test_cookies`
Expected: FAIL — `ModuleNotFoundError: No module named 'ui_core.cookies'`.

- [ ] **Step 3: Create `ui_core/cookies.py`**

```python
"""Shared cookie policy for the web chat apps.

Single source of truth for cookie names and the attribute policy applied to
Flask ``response.set_cookie(...)``. Each app passes its own ``secure`` and
``max_age`` (which come from that app's config) into ``default_cookie_kwargs``.
"""

from __future__ import annotations

import uuid

SESSION_COOKIE_NAME = "tutor_session_id"
USERNAME_COOKIE_NAME = "tutor_username"


def new_session_id() -> str:
    """Generate a fresh anonymous session id (UUIDv4)."""
    return str(uuid.uuid4())


def default_cookie_kwargs(*, secure: bool, max_age: int) -> dict:
    """Cookie attribute kwargs for Flask ``response.set_cookie(...)``.

    HttpOnly + SameSite=None + Secure + Partitioned (CHIPS) for iframe /
    third-party context. ``secure`` and ``max_age`` come from the app's config.
    """
    return {
        "httponly": True,
        "samesite": "None",
        "secure": secure,
        "max_age": max_age,
        "path": "/",
        "partitioned": True,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m ui_core.test_cookies`
Expected: PASS — `2 test functions`, `5 passed, 0 failed`.

- [ ] **Step 5: Replace `main_ui/cookies.py` with a wrapper**

```python
"""Cookie names + policy for main_ui — thin wrapper over ui_core.cookies.

Re-exports the shared constants and helpers; ``default_cookie_kwargs()`` stays a
no-arg call that reads main_ui's config, so route call sites are unchanged.
"""

from __future__ import annotations

from ui_core.cookies import (  # re-exported for existing importers
    SESSION_COOKIE_NAME,
    USERNAME_COOKIE_NAME,
    new_session_id,
    default_cookie_kwargs as _base_cookie_kwargs,
)
from main_ui.config import load_config

__all__ = ["SESSION_COOKIE_NAME", "USERNAME_COOKIE_NAME", "new_session_id", "default_cookie_kwargs"]


def default_cookie_kwargs() -> dict:
    """Cookie kwargs using main_ui's configured secure flag and max-age."""
    config = load_config()
    return _base_cookie_kwargs(secure=config.cookie_secure, max_age=config.cookie_max_age_seconds)
```

- [ ] **Step 6: Replace `sandbox_ui/cookies.py` with a wrapper**

```python
"""Cookie names + policy for sandbox_ui — thin wrapper over ui_core.cookies."""

from __future__ import annotations

from ui_core.cookies import (  # re-exported for existing importers
    SESSION_COOKIE_NAME,
    USERNAME_COOKIE_NAME,
    new_session_id,
    default_cookie_kwargs as _base_cookie_kwargs,
)
from sandbox_ui.config import load_config

__all__ = ["SESSION_COOKIE_NAME", "USERNAME_COOKIE_NAME", "new_session_id", "default_cookie_kwargs"]


def default_cookie_kwargs() -> dict:
    """Cookie kwargs using sandbox_ui's configured secure flag and max-age."""
    config = load_config()
    return _base_cookie_kwargs(secure=config.cookie_secure, max_age=config.cookie_max_age_seconds)
```

- [ ] **Step 7: Verify the app wrappers keep their surface + behavior**

Run:
```bash
DATABASE_URL="sqlite:///tmp_verify.db" python -c "
import main_ui.cookies as mc, sandbox_ui.cookies as sc
for m in (mc, sc):
    assert m.SESSION_COOKIE_NAME=='tutor_session_id'
    assert m.USERNAME_COOKIE_NAME=='tutor_username'
    k=m.default_cookie_kwargs()
    assert set(k)=={'httponly','samesite','secure','max_age','path','partitioned'}, k
    assert isinstance(k['secure'], bool) and isinstance(k['max_age'], int)
print('cookie wrappers OK')
"
```
Expected: prints `cookie wrappers OK`. (If `load_config()` needs more env than `DATABASE_URL`, add the minimal vars for the command only; do not change config files.)

- [ ] **Step 8: Commit**

```bash
git add ui_core/cookies.py ui_core/test_cookies.py main_ui/cookies.py sandbox_ui/cookies.py
git commit -m "refactor(web): share cookie policy via ui_core.cookies"
```

---

## Notes for the implementer

- This is Phase 1 of a multi-phase `ui_core` consolidation (see
  `docs/superpowers/specs/2026-07-02-ui-core-shared-ui-design.md`). Later phases
  extract services, the app factory, and the chat/TutorBridge layer, and add the
  URL-map-snapshot verification harness. Do NOT pull that work forward.
- `database_ui` has no `cookies.py` — do not create one for it.
- If any verification command fails because `load_config()` requires environment
  variables, supply them **only** on the command line for that check. Config
  extraction is a later phase; do not modify any `config.py` here.
- Keep the per-app `db/session.py` and `cookies.py` as the public surface — other
  modules import `from <app>.db.session import get_session` and
  `from <app>.cookies import SESSION_COOKIE_NAME`, and those must keep working
  unchanged.
