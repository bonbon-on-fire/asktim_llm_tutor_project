# Provider-outage weekly-report markers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist tutor outages as dated episodes and flag the affected days on the weekly report's Daily-activity chart.

**Architecture:** `main_ui` records each `service_health` degraded episode into a new append-only `provider_outage` table at its three existing open/close transitions. `database_ui` reads that table (shared Postgres) live per request, folds outages overlapping the week into `payload.live.outages`, and `analytics.js` draws a ⚠ marker over each affected day bar.

**Tech Stack:** Python 3, SQLAlchemy 2.x, Alembic, Flask, vanilla JS (inline SVG). main_ui tests are standalone scripts (`_check`/`print`, run via `python -m ...`); database_ui tests are pytest.

**Spec:** `docs/superpowers/specs/2026-09-03-provider-outage-weekly-report-markers-design.md`

## Global Constraints

- **main_ui owns the schema.** New table + model live in `main_ui`; `database_ui` only maps a **read-only** model to the same table and runs no migrations.
- **Migration chains off head `c4e8a1b6d902`** (`add_service_health`). Alembic runs via `alembic -c main_ui/db/migrations/alembic.ini upgrade head`.
- **Capture must never raise.** All three capture hooks are try/except-guarded and log-and-swallow; a capture failure must not break a chat turn. Callers commit the session.
- **At most one open incident** (`ended_at IS NULL`) exists at a time — single service, single degraded flag.
- **TZ:** week bounds and day bucketing use `America/New_York` (`database_ui.analytics.weeks.TZ`), consistent with `messages_by_day`.
- **Outages are global, not course-scoped:** they live in `payload.live` (computed per request from `g.db`), never in the course-filtered cache.
- Timestamps are stored tz-aware UTC (`DateTime(timezone=True)`), matching `ServiceHealth`.

---

### Task 1: `provider_outage` table — model + migration (main_ui)

**Files:**
- Modify: `main_ui/db/models.py` (add `ProviderOutage` after `ServiceHealth`, ~line 140)
- Create: `main_ui/db/migrations/versions/a1c3e5f7b209_add_provider_outage.py`

**Interfaces:**
- Produces: `main_ui.db.models.ProviderOutage` with columns `id: int` (PK, autoincrement), `started_at: datetime` (not null, tz-aware), `ended_at: datetime | None`, `reason: str | None`, `updated_at: datetime` (not null, `default=_utcnow, onupdate=_utcnow`). `__tablename__ = "provider_outage"`.

- [ ] **Step 1: Add the model**

In `main_ui/db/models.py`, after the `ServiceHealth` class, add (imports `Integer, DateTime, Text` are already imported at the top of the file; `_utcnow` is already imported from `ui_core.db.models_common`):

```python
class ProviderOutage(Base):
    """Append-only log of tutor degraded episodes, one row per outage.

    Written by ``main_ui/services/service_health.py`` when the shared
    ``service_health`` degraded flag opens and closes; read by the database_ui
    weekly report to mark affected days. At most one row is open
    (``ended_at IS NULL``) at a time, since there is a single degraded flag.
    """

    __tablename__ = "provider_outage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
```

- [ ] **Step 2: Verify the model imports and builds a table**

Run: `python -c "from main_ui.db.models import Base, ProviderOutage; from sqlalchemy import create_engine; e=create_engine('sqlite:///:memory:'); Base.metadata.create_all(e); print('provider_outage' in Base.metadata.tables)"`
Expected: prints `True`.

- [ ] **Step 3: Write the migration**

Create `main_ui/db/migrations/versions/a1c3e5f7b209_add_provider_outage.py`:

```python
"""add provider_outage incident log

Append-only history of tutor degraded episodes (see
main_ui/services/service_health.py and the design spec
docs/superpowers/specs/2026-09-03-provider-outage-weekly-report-markers-design.md).
Starts empty; rows are written as outages open and close. The database_ui
weekly report reads this table to mark affected days on the activity chart.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c3e5f7b209"
down_revision: Union[str, Sequence[str], None] = "c4e8a1b6d902"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "provider_outage",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("provider_outage")
```

- [ ] **Step 4: Verify the migration chain is linear (single head)**

Run: `alembic -c main_ui/db/migrations/alembic.ini heads`
Expected: exactly one head, `a1c3e5f7b209 (head)`. If two heads appear, the `down_revision` is wrong — it must be `c4e8a1b6d902`.

- [ ] **Step 5: Commit**

```bash
git add main_ui/db/models.py main_ui/db/migrations/versions/a1c3e5f7b209_add_provider_outage.py
git commit -m "feat(outage): add provider_outage incident-log table"
```

---

### Task 2: Capture hooks in service_health.py (main_ui)

**Files:**
- Modify: `main_ui/services/service_health.py` (import `ProviderOutage`; add helpers; call them at the three transitions in `record_chat_outcome` and `current_degraded`)
- Modify: `main_ui/services/test_service_health.py` (add cases + call from `main()`)

**Interfaces:**
- Consumes: `main_ui.db.models.ProviderOutage` (Task 1); existing `record_chat_outcome(session, ok, *, threshold=None, now=None)` and `current_degraded(session, *, cooldown_seconds=None, now=None)`.
- Produces: module-internal `_open_outage(session, now)` and `_close_open_outage(session, ended_at)` — both best-effort (swallow errors), called from the transition points. No public signature change.

- [ ] **Step 1: Write the failing tests**

Add to `main_ui/services/test_service_health.py`, and call `ok &= _test_outage_log()` inside `main()` before the final `return`. `ProviderOutage` import goes next to the existing `from main_ui.db.models import Base, ServiceHealth` (make it `Base, ProviderOutage, ServiceHealth`):

```python
def _open_outages(s):
    return s.query(ProviderOutage).filter(ProviderOutage.ended_at.is_(None)).all()


def _all_outages(s):
    return s.query(ProviderOutage).order_by(ProviderOutage.started_at).all()


def _test_outage_log() -> bool:
    ok = True
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    now = _fixed_now()

    # crossing threshold opens exactly one outage row at started_at=now
    with Session(engine) as s:
        for i in range(5):
            svc.record_chat_outcome(s, ok=False, threshold=5, now=now + timedelta(seconds=i))
        s.commit()
        rows = _all_outages(s)
        trip = now + timedelta(seconds=4)
        ok &= _check("threshold opens one open outage",
                     len(rows) == 1 and rows[0].ended_at is None and rows[0].started_at == trip,
                     f"rows={[(r.started_at, r.ended_at) for r in rows]}")

        # staying degraded (another failure) does NOT open a second row
        svc.record_chat_outcome(s, ok=False, threshold=5, now=now + timedelta(seconds=5))
        s.commit()
        ok &= _check("staying degraded opens no second row", len(_all_outages(s)) == 1)

        # a success while degraded closes the open row at ended_at=success time
        close_at = now + timedelta(seconds=6)
        svc.record_chat_outcome(s, ok=True, threshold=5, now=close_at)
        s.commit()
        rows = _all_outages(s)
        ok &= _check("success closes open outage at success time",
                     len(rows) == 1 and rows[0].ended_at == close_at,
                     f"ended_at={rows[0].ended_at}")

    # a success while healthy opens/closes nothing
    with Session(engine) as s2:
        Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
        svc.record_chat_outcome(s2, ok=True, threshold=5, now=now)
        s2.commit()
        ok &= _check("healthy success logs no outage", len(_all_outages(s2)) == 0)

    # lazy expiry closes the open row at ended_at=last_failure_at
    with Session(engine) as s3:
        Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
        for i in range(5):
            svc.record_chat_outcome(s3, ok=False, threshold=5, now=now + timedelta(seconds=i))
        s3.commit()
        last_fail = now + timedelta(seconds=4)
        # far enough past last_failure_at that lazy expiry fires (cooldown default 90s)
        svc.current_degraded(s3, cooldown_seconds=90, now=now + timedelta(seconds=200))
        s3.commit()
        rows = _all_outages(s3)
        ok &= _check("lazy expiry closes outage at last_failure_at",
                     len(rows) == 1 and rows[0].ended_at == last_fail,
                     f"ended_at={rows[0].ended_at} last_fail={last_fail}")

    # capture is best-effort: a broken outage write does not break record_chat_outcome
    with Session(engine) as s4:
        Base.metadata.drop_all(engine); Base.metadata.create_all(engine)
        orig = svc._open_outage
        svc._open_outage = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        try:
            for i in range(5):
                svc.record_chat_outcome(s4, ok=False, threshold=5, now=now + timedelta(seconds=i))
            s4.commit()
            row = s4.get(ServiceHealth, 1)
            ok &= _check("outage-write failure is swallowed", row.degraded is True)
        except Exception as exc:  # noqa: BLE001
            ok &= _check("outage-write failure is swallowed", False, f"raised {exc!r}")
        finally:
            svc._open_outage = orig
    return ok
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m main_ui.services.test_service_health`
Expected: FAIL lines for the new outage checks (e.g. `AttributeError: module ... has no attribute '_open_outage'`, or the outage-row asserts fail) and a nonzero exit.

- [ ] **Step 3: Add the capture helpers**

In `main_ui/services/service_health.py`, add the `ProviderOutage` import next to `from main_ui.db.models import ServiceHealth` (make it `ServiceHealth, ProviderOutage`), and add these helpers below `_SINGLETON_ID`:

```python
def _open_outage(session: Session, now: datetime) -> None:
    """Record the start of a degraded episode (best-effort).

    No-op if an episode is already open, so a second trip can't double-log.
    """
    exists = (
        session.query(ProviderOutage)
        .filter(ProviderOutage.ended_at.is_(None))
        .first()
    )
    if exists is None:
        session.add(ProviderOutage(started_at=now, ended_at=None, reason=None))


def _close_open_outage(session: Session, ended_at: datetime) -> None:
    """Close the open degraded episode, if any (best-effort)."""
    row = (
        session.query(ProviderOutage)
        .filter(ProviderOutage.ended_at.is_(None))
        .order_by(ProviderOutage.started_at.desc())
        .first()
    )
    if row is not None:
        row.ended_at = ended_at
        row.updated_at = ended_at


def _safe(fn, *args) -> None:
    """Run a capture helper without ever propagating — a logging failure must
    not break the chat turn that triggered it."""
    try:
        fn(*args)
    except Exception:  # noqa: BLE001 - capture is best-effort telemetry
        pass
```

- [ ] **Step 4: Wire the three transitions**

In `record_chat_outcome`, capture the prior degraded state and hook both transitions. Replace the `if ok: ... else: ...` block body so it reads:

```python
    was_degraded = bool(row.degraded)
    if ok:
        row.consecutive_failures = 0
        row.last_success_at = now
        row.degraded = False
        row.degraded_since = None
        if was_degraded:
            _safe(_close_open_outage, session, now)
    else:
        row.consecutive_failures = (row.consecutive_failures or 0) + 1
        row.last_failure_at = now
        if row.consecutive_failures >= threshold and not row.degraded:
            row.degraded = True
            row.degraded_since = now
            _safe(_open_outage, session, now)
    row.updated_at = now
    return row
```

In `current_degraded`, at the lazy-expiry reset (where `row.degraded = False` is set after the cooldown check), close the open outage at the true end (`last_failure_at`, falling back to `now`):

```python
    if reference is not None and (now - reference) > timedelta(seconds=cooldown_seconds):
        _safe(_close_open_outage, session, _as_aware(row.last_failure_at) or now)
        row.degraded = False
        row.degraded_since = None
        row.consecutive_failures = 0
        row.updated_at = now
        return False
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m main_ui.services.test_service_health`
Expected: all lines PASS, exit 0 (existing state-machine checks still pass; new outage checks pass).

- [ ] **Step 6: Commit**

```bash
git add main_ui/services/service_health.py main_ui/services/test_service_health.py
git commit -m "feat(outage): log degraded episodes to provider_outage on open/close"
```

---

### Task 3: Read path — read-only model, fetch_outages, live_stats wiring (database_ui)

**Files:**
- Modify: `database_ui/db/models.py` (add read-only `ProviderOutage`)
- Modify: `database_ui/analytics/data.py` (add `Outage` dataclass + `fetch_outages`)
- Modify: `database_ui/services/analytics.py` (attach `stats["outages"]` in `live_stats`)
- Test: `database_ui/analytics/tests/test_data.py` (add `fetch_outages` cases)

**Interfaces:**
- Consumes: the `provider_outage` table (Task 1); `Week` with `.start_utc` / `.end_utc` (UTC, half-open) and `TZ`.
- Produces: `database_ui.analytics.data.fetch_outages(db: Session, week: Week) -> list[dict]`, each dict `{"start": iso_str, "end": iso_str | None, "reason": str | None}` in `TZ`, ordered by start. `live_stats` result gains key `"outages": list[dict]` (global, unaffected by `courses`).

- [ ] **Step 1: Add the read-only model**

In `database_ui/db/models.py`, mirror the existing read-only pattern (its own `Base`; `Integer, DateTime, Text` are already imported there — confirm and add any missing to the existing `from sqlalchemy import (...)` block):

```python
class ProviderOutage(Base):
    """Read-only view of main_ui's provider_outage incident log (shared DB)."""

    __tablename__ = "provider_outage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 2: Write the failing test**

Add to `database_ui/analytics/tests/test_data.py` (it already uses the `session` fixture / `SessionLocal`; if not present in that file, copy the `session` fixture from `test_weekly.py`). `conftest.py` runs `Base.metadata.create_all(engine)`, so the `provider_outage` table exists in the test DB automatically.

```python
from datetime import datetime, timezone, timedelta

from database_ui.analytics.data import fetch_outages
from database_ui.analytics.weeks import week_containing
from database_ui.db.models import ProviderOutage


def _outage(s, start, end):
    s.add(ProviderOutage(started_at=start, ended_at=end, reason=None))
    s.commit()


def test_fetch_outages_overlap(session):
    # Week containing 2026-08-12 (a Wednesday) -> ET Sun 08-09 .. Sat 08-15.
    week = week_containing(datetime(2026, 8, 12).date())
    inside = datetime(2026, 8, 12, 18, tzinfo=timezone.utc)
    _outage(session, inside, inside + timedelta(hours=2))          # wholly inside
    _outage(session, week.start_utc - timedelta(hours=1),
            week.start_utc + timedelta(hours=1))                    # spans into week start
    _outage(session, datetime(2026, 8, 13, 20, tzinfo=timezone.utc), None)  # ongoing
    _outage(session, week.end_utc + timedelta(hours=1),
            week.end_utc + timedelta(hours=2))                      # entirely after -> excluded

    out = fetch_outages(session, week)
    assert len(out) == 3
    assert out[0]["start"] <= out[1]["start"] <= out[2]["start"]   # ordered by start
    assert any(o["end"] is None for o in out)                      # ongoing preserved
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest database_ui/analytics/tests/test_data.py::test_fetch_outages_overlap -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_outages'`.

- [ ] **Step 4: Implement `fetch_outages`**

In `database_ui/analytics/data.py`, add the import `from database_ui.db.models import Conversation, Message, ProviderOutage` (extend the existing import), and add:

```python
def fetch_outages(db: Session, week: Week) -> list[dict]:
    """Degraded episodes overlapping ``week`` (UTC half-open), in report TZ.

    Overlap = started before the week ends AND (still open OR ended at/after the
    week starts). Timestamps are emitted as ISO strings in ``TZ`` so the client
    buckets them by the same ET calendar day as the activity bars; ``end`` is
    ``None`` for an ongoing outage.
    """
    stmt = (
        select(ProviderOutage)
        .where(
            ProviderOutage.started_at < week.end_utc,
            (ProviderOutage.ended_at.is_(None))
            | (ProviderOutage.ended_at >= week.start_utc),
        )
        .order_by(ProviderOutage.started_at.asc())
    )
    rows = db.execute(stmt).scalars().all()
    return [
        {
            "start": r.started_at.astimezone(TZ).isoformat(),
            "end": r.ended_at.astimezone(TZ).isoformat() if r.ended_at else None,
            "reason": r.reason,
        }
        for r in rows
    ]
```

`TZ` is already imported in `data.py` (`from database_ui.analytics.weeks import ... TZ` — confirm; add if missing). `select` is already imported.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest database_ui/analytics/tests/test_data.py::test_fetch_outages_overlap -v`
Expected: PASS.

- [ ] **Step 6: Wire into `live_stats`**

In `database_ui/services/analytics.py`, add to `live_stats` before `return stats` (outages are global — pass no `courses`):

```python
    stats["outages"] = data_mod.fetch_outages(db, week)
```

- [ ] **Step 7: Verify live_stats carries outages**

Run: `pytest database_ui/analytics/tests/ -k "data or weekly" -q`
Expected: PASS (no regressions; new test included).

- [ ] **Step 8: Commit**

```bash
git add database_ui/db/models.py database_ui/analytics/data.py database_ui/services/analytics.py database_ui/analytics/tests/test_data.py
git commit -m "feat(outage): expose week outages in live analytics payload"
```

---

### Task 4: Day markers on the Daily-activity chart (frontend)

**Files:**
- Modify: `database_ui/static/js/analytics.js` (`barChart` + the Daily-activity render at ~line 347)
- Modify: `database_ui/static/css/analytics.css` (marker style)
- Modify: `database_ui/templates/index.html` (bump `analytics.js` `v=41`→`42` and `analytics.css` `v=27`→`28`)

**Interfaces:**
- Consumes: `payload.live.outages` (Task 3) — `[{start, end, reason}]`, ISO strings in ET, `end` may be `null`; and the existing Sun–Sat `weekSeries` day cells keyed by `payload.week.key`.

- [ ] **Step 1: Add a day-affected helper**

In `analytics.js`, near `weekSeries`, add a helper that returns, for a given Sun-key, the set of ET `YYYY-MM-DD` day strings each outage touches, plus a per-day tooltip. Compute affected days by walking from the outage start date to its end date (or "ongoing"):

```javascript
  // Map outages to the ET day-strings they touch, with a per-day tooltip.
  // Returns { "YYYY-MM-DD": "Provider outage · 14:05–16:15 (2h10m) · reason" }.
  // o.start / o.end are ET-offset ISO strings (e.g. "2026-08-12T14:05:00-04:00").
  // Read the wall-clock and calendar day straight off the STRING — never via
  // Date.toISOString(), which converts to UTC and can shift a late-evening
  // outage onto the next ET day. Duration uses the real instants (DST-safe).
  function outageDays(outages) {
    const out = {};
    (outages || []).forEach((o) => {
      if (!o.start) return;
      const hhmm = (iso) => iso.slice(11, 16);            // ET wall-clock, verbatim
      const dur = o.end ? Math.round((new Date(o.end) - new Date(o.start)) / 60000) : null;
      const span = o.end
        ? `${hhmm(o.start)}–${hhmm(o.end)} (${Math.floor(dur / 60)}h${String(dur % 60).padStart(2, "0")}m)`
        : `${hhmm(o.start)}–ongoing`;
      const tip = `Provider outage · ${span}${o.reason ? " · " + o.reason : ""}`;
      // Walk ET calendar days by date-string, start..end inclusive. Parse the
      // date-only slice as UTC midnight and compare via the same UTC accessor,
      // so the walk is internally consistent and no boundary day can shift.
      const endDay = (o.end || o.start).slice(0, 10);
      const key = (dt) => dt.toISOString().slice(0, 10);
      for (let d = new Date(o.start.slice(0, 10) + "T00:00:00Z"); key(d) <= endDay; d.setUTCDate(d.getUTCDate() + 1)) {
        const k = key(d);
        out[k] = out[k] ? out[k] + "; " + tip : tip;
      }
    });
    return out;
  }
```

- [ ] **Step 2: Pass affected days into `barChart` and draw the marker**

Give `barChart` an optional `opts.marks` — `{ "<day-label or index>": "tooltip" }` keyed by bar index — and after drawing each bar's value/label, draw a marker when that bar is marked. In the Daily-activity render (~line 347), build the marks by matching each Sun–Sat cell to its ET day key.

In `barChart`, inside the per-bar loop where `d` is drawn at index `i`, after the value/label text, add:

```javascript
      if (opts.marks && opts.marks[i]) {
        const mk = el("text", { _svg: true, x: x + bw / 2, y: y - 16,
          "text-anchor": "middle", class: "chart-mark" }, ["⚠"]); // ⚠
        mk.appendChild(el("title", { _svg: true }, [opts.marks[i]]));
        svg.appendChild(mk);
      }
```

At the Daily-activity call site, replace the current `barChart(byDay, {...})` with marks computed from the week's Sunday and the day series:

```javascript
    const days = outageDays((payload.live && payload.live.outages) || []);
    // byDay entries are Sun..Sat in order; recover each cell's ET date key.
    const [wy, wm, wd] = payload.week.key.split("-").map(Number);
    const wkBase = Date.UTC(wy, wm - 1, wd);
    const marks = {};
    byDay.forEach((_, i) => {
      const iso = new Date(wkBase + i * 86400000).toISOString().slice(0, 10);
      if (days[iso]) marks[i] = days[iso];
    });
    root.appendChild(card("Daily activity", barChart(byDay, {
      label: "Daily message activity, Sunday through Saturday", marks })));
```

- [ ] **Step 3: Style the marker**

In `analytics.css`, add near the other `.chart-*` rules (sibling to `.chart-val` at line 272). There is no `--danger` var in this file, so use a literal that reads on both themes; reuse the existing `--chart-val-size`:

```css
.chart-mark { fill: #c0392b; font-size: var(--chart-val-size, 14px); }
```

- [ ] **Step 4: Bump cache-bust versions**

In `database_ui/templates/index.html`: `css/analytics.css` `v='27'` → `v='28'`; `js/analytics.js` `v='41'` → `v='42'`.

- [ ] **Step 5: Verify in the running app**

Use the `run` skill to launch database_ui against a DB that has a `provider_outage` row inside the displayed week (insert one manually if needed). Confirm: the affected day bar shows a ⚠ above it, hovering shows the tooltip (`Provider outage · …`), a week with no outages renders identically to before, and an ongoing outage shows `…–ongoing`. Also load a week whose `payload.live.outages` is empty to confirm no marker and no JS error in the console.

- [ ] **Step 6: Commit**

```bash
git add database_ui/static/js/analytics.js database_ui/static/css/analytics.css database_ui/templates/index.html
git commit -m "feat(outage): mark outage-affected days on the weekly activity chart"
```

---

## Self-Review

**Spec coverage:**
- Spec §1 `provider_outage` table → Task 1. ✓
- Spec §2 three capture transitions (open, close-on-success, close-on-expiry) with best-effort guard → Task 2 (Steps 3–4, guard test Step 1). ✓
- Spec §3 read-only model + week-overlap query + payload list → Task 3. Note: spec named `stats.py` as the query home, but `stats.py` is pure/no-DB by design; the DB query lives in `data.py` and is attached in `live_stats` (`payload.live.outages`) instead. This is a location refinement, not a behavior change — outages are global and `live_stats` is the DB-backed, non-course-scoped path where `messages_by_day` already lives. ✓
- Spec §4 marker + tooltip on Daily-activity chart, no-op when empty, cache-bust bump → Task 4. ✓
- Spec §5 test matrix → Task 2 Step 1 (main_ui) + Task 3 Step 2 (database_ui) + Task 4 Step 5 (manual visual). ✓
- Spec "out of scope" (`reason` stays NULL, no summary line, no backfill) → honored: `_open_outage` writes `reason=None`; no summary UI; migration seeds nothing. ✓

**Placeholder scan:** No TBD/TODO; every code step has concrete code. Manual verification (Task 4 Step 5) is explicit about what to check because there is no JS test harness for `analytics.js` in this repo.

**Type consistency:** `ProviderOutage` columns match across Task 1 (main_ui write model) and Task 3 (database_ui read model — subset, read-only). `fetch_outages(db, week) -> list[dict]` with keys `start/end/reason` is produced in Task 3 and consumed in Task 4 (`outageDays` reads `o.start/o.end/o.reason`). `_open_outage`/`_close_open_outage` defined and called in Task 2, and referenced by name in the guard test. `live_stats` key `outages` set in Task 3 Step 6, read as `payload.live.outages` in Task 4 Step 2.

**Verified against the codebase:** `--chart-val-size` exists (`.chart-val`, analytics.css:272); `--danger` does **not**, so the marker rule uses a literal `#c0392b`. `database_ui/db/models.py` already imports `Integer`/`DateTime`/`Text`; `data.py` already imports `TZ`, `Week`, and `select`. Migration head is `c4e8a1b6d902` (`alembic heads` must show a single head after Task 1). The `outageDays` day-walk reads calendar days and wall-clock straight off the ET-offset ISO strings to avoid a UTC day-boundary shift.
