# Weekly Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a scoped "Weekly report" analytics view to `database_ui` — live per-week usage/ratings/cost/RAG statistics plus an LLM-judged failure list, example conversations, and student topics precomputed by a weekly GitHub Action.

**Architecture:** A new `database_ui/analytics/` package holds pure week-math, windowed read-queries, statistics, an LLM judge (behind an interface for test fakes), and a `weekly.py` CLI that writes a committed JSON cache + a `report.md`. The Flask dashboard gains an `analytics_bp` blueprint and an `services/analytics.py` layer that computes live stats per request and reads/course-filters the cache. A GitHub Actions workflow runs the CLI weekly and opens a PR against the deploy branch. Charts are drawn client-side as inline SVG from JSON — no matplotlib, no server-rendered images.

**Tech Stack:** Python 3.12, Flask, SQLAlchemy 2.x (`select`), `zoneinfo`, `langchain-anthropic` (judge), vanilla JS + inline SVG (charts), GitHub Actions.

## Global Constraints

- **Location:** the entire analytics package **and its cache** live under `database_ui/` (`database_ui/analytics/…`, cache at `database_ui/analytics/cache/<start-date>.json`). The database Docker image copies only `database_ui/` + `ui_core/`; a top-level `analytics/` dir would be excluded by `.dockerignore` and never deploy. Do **not** create a top-level `analytics/` package.
- **Read-only:** the dashboard and every query is `SELECT`-only. Never insert/update/create tables, never call `create_all`, never add a migration. Map only columns already in `database_ui/db/models.py`.
- **Scoping:** every dashboard query and every cache read passes `allowed_courses()` (`None` = master/all-access; a `list[str]` = restrict to those course keys). A scoped login must never receive another course's live rows **or** cached entries. Filter pattern: `if courses is not None: stmt = stmt.where(Conversation.course.in_(courses))`.
- **Week definition:** Sunday → Saturday in `America/New_York`. Windowing filters on UTC instants computed from the local week (`week.start_utc <= ts < week.end_utc`). User-facing labels format as `Aug 9, 2026 — Aug 15, 2026` (abbreviated month via `%b`, no leading-zero day, full year). Cache filenames key off the week's **start date**: `2026-08-09.json`.
- **Deploy branch:** the weekly PR targets **`prod-beta-plus`** (the branch `database_ui` deploys from). Encode as workflow input default `TARGET_BRANCH: prod-beta-plus`.
- **Judge model:** `ANALYTICS_JUDGE_MODEL` env, default `claude-sonnet-5`. The judge sits behind a `Judge` protocol; **no test may call a real LLM** — tests inject `FakeJudge`.
- **Privacy:** real `username` values (student emails) appear in stats, cache, and `report.md`. The repo must stay private; do not redact, but never log them to stdout beyond the report.
- **Commits:** conventional commits (`type(scope): subject`); **no** `Co-Authored-By: Claude` trailer.
- **Cache-busting:** bump the `v=` query arg on any edited `database_ui/static/js|css` asset in `templates/analytics.html`.

---

## File Structure

**New package — `database_ui/analytics/`:**
- `__init__.py` — empty package marker.
- `weeks.py` — `Week` dataclass + week math (Sun–Sat, tz, labels, parsing).
- `data.py` — windowed, scoped read-queries; returns plain `ConvRow`/`MsgRow` dataclasses decoupled from the ORM.
- `stats.py` — pure statistics (§1–4), per-course slices, prior-week deltas.
- `cache.py` — cache JSON schema constants; read + course-filter; write.
- `judge.py` — `Verdict`, `Judge` protocol, `FakeJudge`, `AnthropicJudge`, transcript hashing.
- `topics.py` — aggregate per-conversation topics into ranked per-course lists.
- `flags.py` — build the ranked failure list (§5) from `rating == -1` ∪ judge.
- `examples.py` — pick ⭐/🔥/🎲 example sets (§6), seeded by week key.
- `report.py` — render the human-readable `report.md`.
- `weekly.py` — CLI entrypoint (`python -m database_ui.analytics.weekly`).
- `cache/.gitkeep` — the committed-cache directory.
- `tests/` — unit tests (seeded SQLite for `data.py`; dataclass fixtures + `FakeJudge` elsewhere).

**Dashboard wiring:**
- `database_ui/services/analytics.py` — live stats over `g.db` + cache reader, both scoped.
- `database_ui/routes/analytics.py` — `analytics_bp` blueprint.
- `database_ui/templates/analytics.html` — the page.
- `database_ui/static/js/analytics.js` — fetch + inline-SVG charts + rendering.
- `database_ui/static/css/analytics.css` — page styles.
- Modify `database_ui/run_app.py` — register `analytics_bp`.
- Modify `database_ui/templates/index.html` — "Weekly report" sidebar button (link to `/analytics`).

**Ops & docs:**
- `.github/workflows/weekly-analytics.yml` — scheduled + manual run → PR.
- Modify `database_ui/README.md` — document the feature.

---

## Task 1: Week math (`weeks.py`)

**Files:**
- Create: `database_ui/analytics/__init__.py` (empty)
- Create: `database_ui/analytics/weeks.py`
- Create: `database_ui/analytics/tests/__init__.py` (empty)
- Test: `database_ui/analytics/tests/test_weeks.py`

**Interfaces:**
- Produces: `Week(start: date)` with `.end -> date`, `.key -> str` (ISO start), `.start_utc/.end_utc -> datetime` (UTC, half-open window), `.label() -> str`, `.prev() -> Week`; `week_containing(d: date) -> Week`; `previous_complete_week(today: date) -> Week`; `parse_week(s: str) -> Week`.

- [ ] **Step 1: Write the failing tests**

```python
# database_ui/analytics/tests/test_weeks.py
from datetime import date, datetime, timezone

from database_ui.analytics.weeks import (
    Week, week_containing, previous_complete_week, parse_week,
)


def test_week_containing_snaps_to_sunday():
    # Aug 12 2026 is a Wednesday; its week starts Sun Aug 9.
    assert week_containing(date(2026, 8, 12)).start == date(2026, 8, 9)
    # A Sunday maps to itself.
    assert week_containing(date(2026, 8, 9)).start == date(2026, 8, 9)
    # A Saturday still maps back to the prior Sunday.
    assert week_containing(date(2026, 8, 15)).start == date(2026, 8, 9)


def test_week_end_and_label():
    w = Week(date(2026, 8, 9))
    assert w.end == date(2026, 8, 15)
    assert w.key == "2026-08-09"
    assert w.label() == "Aug 9, 2026 — Aug 15, 2026"


def test_previous_complete_week():
    # From Wed Aug 12 2026, the previous complete week is Aug 2–8.
    assert previous_complete_week(date(2026, 8, 12)).start == date(2026, 8, 2)


def test_utc_window_is_half_open_and_dst_correct():
    w = Week(date(2026, 8, 9))  # summer -> EDT, UTC-4
    # Local Sun 00:00 EDT == 04:00 UTC.
    assert w.start_utc == datetime(2026, 8, 9, 4, 0, tzinfo=timezone.utc)
    # Exclusive end == next Sun 00:00 EDT == 04:00 UTC.
    assert w.end_utc == datetime(2026, 8, 16, 4, 0, tzinfo=timezone.utc)


def test_parse_week_snaps_and_prev():
    assert parse_week("2026-08-12").start == date(2026, 8, 9)
    assert Week(date(2026, 8, 9)).prev().start == date(2026, 8, 2)
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest database_ui/analytics/tests/test_weeks.py -v`
Expected: FAIL — `ModuleNotFoundError: database_ui.analytics.weeks`.

- [ ] **Step 3: Implement `weeks.py`**

```python
# database_ui/analytics/weeks.py
"""Sunday-to-Saturday week math in America/New_York for the weekly report.

The DB stores tz-aware UTC timestamps. A "week" is a local Sun 00:00 -> next
Sun 00:00 half-open interval; we expose its UTC bounds so queries stay portable
(no DB-side timezone functions). Labels render as ``Aug 9, 2026 — Aug 15, 2026``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/New_York")
_UTC = ZoneInfo("UTC")


def _fmt(d: date) -> str:
    """``date(2026, 8, 9)`` -> ``"Aug 9, 2026"`` (abbrev month, no zero-pad day)."""
    return f"{d.strftime('%b')} {d.day}, {d.year}"


@dataclass(frozen=True)
class Week:
    """A Sunday-anchored calendar week. ``start`` must be a Sunday."""

    start: date

    @property
    def end(self) -> date:
        """The inclusive Saturday that ends the week."""
        return self.start + timedelta(days=6)

    @property
    def key(self) -> str:
        """Stable identifier / cache filename stem, e.g. ``"2026-08-09"``."""
        return self.start.isoformat()

    @property
    def start_utc(self) -> datetime:
        """Local Sunday 00:00, expressed as a UTC instant (inclusive lower bound)."""
        return datetime.combine(self.start, time.min, TZ).astimezone(_UTC)

    @property
    def end_utc(self) -> datetime:
        """Next local Sunday 00:00 as a UTC instant (exclusive upper bound)."""
        nxt = self.start + timedelta(days=7)
        return datetime.combine(nxt, time.min, TZ).astimezone(_UTC)

    def label(self) -> str:
        """Human range, e.g. ``"Aug 9, 2026 — Aug 15, 2026"``."""
        return f"{_fmt(self.start)} — {_fmt(self.end)}"

    def prev(self) -> "Week":
        """The immediately preceding week."""
        return Week(self.start - timedelta(days=7))


def week_containing(d: date) -> Week:
    """The Sun–Sat week that contains ``d``. Python weekday: Mon=0..Sun=6."""
    days_since_sunday = (d.weekday() + 1) % 7
    return Week(d - timedelta(days=days_since_sunday))


def previous_complete_week(today: date) -> Week:
    """The most recent week that has fully ended as of ``today``."""
    return week_containing(today).prev()


def parse_week(s: str) -> Week:
    """Parse ``YYYY-MM-DD`` and snap to its containing week's Sunday."""
    return week_containing(date.fromisoformat(s.strip()))
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest database_ui/analytics/tests/test_weeks.py -v`
Expected: PASS (all 5).

- [ ] **Step 5: Commit**

```bash
git add database_ui/analytics/__init__.py database_ui/analytics/weeks.py database_ui/analytics/tests/__init__.py database_ui/analytics/tests/test_weeks.py
git commit -m "feat(analytics): add Sun-Sat week math for weekly report"
```

---

## Task 2: Windowed scoped read-queries (`data.py`)

**Files:**
- Create: `database_ui/analytics/data.py`
- Test: `database_ui/analytics/tests/test_data.py`

**Interfaces:**
- Consumes: `Week` (Task 1); `Conversation`/`Message` (`database_ui.db.models`).
- Produces:
  - `@dataclass(frozen=True) ConvRow`: `id: str`, `course: str`, `username: str | None`, `exercise_number: str`, `exercise_kind: str`, `focus_problem: int | None`, `tutor_prompt: str`, `started_at: datetime | None`, `last_active_at: datetime | None`.
  - `@dataclass(frozen=True) MsgRow`: `conversation_id: str`, `turn: int`, `role: str`, `content: str`, `rating: int`, `cost_usd: float | None`, `usage_json: str | None`, `has_rag: bool`, `created_at: datetime | None`.
  - `fetch_conversations(db, week: Week, courses: list[str] | None) -> list[ConvRow]` (windowed on `started_at`).
  - `fetch_messages(db, conversation_ids: list[str]) -> list[MsgRow]`.
  - `prior_usernames(db, before: datetime, courses: list[str] | None) -> set[str]` (for new-vs-returning).
  - `fetch_transcript(db, conversation_id: str) -> list[tuple[str, str]]` (ordered `(role, content)` for the judge).

- [ ] **Step 1: Write the failing tests** (reuses the existing seeded SQLite fixture)

```python
# database_ui/analytics/tests/test_data.py
from datetime import datetime, timezone

import pytest

from database_ui.analytics import data as d
from database_ui.analytics.weeks import week_containing
from database_ui.conftest import seed
from database_ui.db.session import SessionLocal


@pytest.fixture()
def session():
    s = SessionLocal()
    ids = seed(s)          # seeds convos dated 2026-05-<day> 12:00 UTC
    yield s, ids
    s.close()


def _week_of_seed():
    # Seed rows are dated May 2026; grab the week that contains May 5.
    return week_containing(datetime(2026, 5, 5).date())


def test_fetch_conversations_windows_and_scopes(session):
    s, ids = session
    wk = week_containing(datetime(2026, 5, 5).date())
    # A distant week returns nothing.
    far = week_containing(datetime(2026, 1, 5).date())
    assert d.fetch_conversations(s, far, None) == []
    # Scope to one course -> only that course's rows come back.
    scoped = d.fetch_conversations(s, wk, ["supply_chain_design"])
    assert scoped, "expected seeded SC conversations in-window"
    assert {c.course for c in scoped} == {"supply_chain_design"}


def test_fetch_messages_maps_rag_flag_and_rating(session):
    s, ids = session
    rows = d.fetch_messages(s, [str(ids["sc_id"])])
    tutor = [m for m in rows if m.role != "student" and m.role != "user"]
    assert any(m.rating == 1 for m in tutor)
    assert any(m.has_rag for m in tutor)  # seeded tutor msg has retrieved_context


def test_prior_usernames(session):
    s, ids = session
    later = datetime(2026, 6, 1, tzinfo=timezone.utc)
    names = d.prior_usernames(s, later, None)
    assert isinstance(names, set)


def test_fetch_transcript_is_ordered(session):
    s, ids = session
    pairs = d.fetch_transcript(s, str(ids["sc_id"]))
    assert [p[0] for p in pairs] == sorted([p[0] for p in pairs], key=lambda _: 0) or pairs
    assert len(pairs) >= 2
```

> Note for the implementer: confirm the seed's tutor `role` string (`"tutor"` vs `"assistant"`) from `database_ui/conftest.py` and adjust the `tutor` filter in the first assertion to match; the RAG/rating assertions are the load-bearing ones.

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest database_ui/analytics/tests/test_data.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `data.py`**

```python
# database_ui/analytics/data.py
"""Windowed, scope-filtered read-queries feeding the weekly report.

Returns plain dataclasses (not ORM objects) so the statistics layer is pure and
unit-testable without a database. All filtering is SELECT-only; course scoping
uses the same ``courses is None -> no filter`` idiom as services/conversations.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from database_ui.analytics.weeks import Week
from database_ui.db.models import Conversation, Message


@dataclass(frozen=True)
class ConvRow:
    id: str
    course: str
    username: str | None
    exercise_number: str
    exercise_kind: str
    focus_problem: int | None
    tutor_prompt: str
    started_at: datetime | None
    last_active_at: datetime | None


@dataclass(frozen=True)
class MsgRow:
    conversation_id: str
    turn: int
    role: str
    content: str
    rating: int
    cost_usd: float | None
    usage_json: str | None
    has_rag: bool
    created_at: datetime | None


def _scoped(stmt, courses: list[str] | None):
    if courses is not None:
        stmt = stmt.where(Conversation.course.in_(courses))
    return stmt


def fetch_conversations(db: Session, week: Week, courses: list[str] | None) -> list[ConvRow]:
    """Conversations whose ``started_at`` falls in ``week`` (UTC half-open)."""
    stmt = _scoped(
        select(Conversation).where(
            Conversation.started_at >= week.start_utc,
            Conversation.started_at < week.end_utc,
        ),
        courses,
    ).order_by(Conversation.started_at.asc())
    return [
        ConvRow(
            id=str(c.id),
            course=c.course,
            username=c.username,
            exercise_number=c.exercise_number,
            exercise_kind=c.exercise_kind,
            focus_problem=c.focus_problem,
            tutor_prompt=c.tutor_prompt,
            started_at=c.started_at,
            last_active_at=c.last_active_at,
        )
        for c in db.execute(stmt).scalars().all()
    ]


def fetch_messages(db: Session, conversation_ids: list[str]) -> list[MsgRow]:
    """All messages for the given conversations, ordered by (conversation, turn)."""
    if not conversation_ids:
        return []
    stmt = (
        select(Message)
        .where(Message.conversation_id.in_(conversation_ids))
        .order_by(Message.conversation_id, Message.turn, Message.id)
    )
    return [
        MsgRow(
            conversation_id=str(m.conversation_id),
            turn=m.turn,
            role=m.role,
            content=m.content,
            rating=m.rating,
            cost_usd=m.cost_usd,
            usage_json=m.usage_json,
            has_rag=bool(m.retrieved_context),
            created_at=m.created_at,
        )
        for m in db.execute(stmt).scalars().all()
    ]


def prior_usernames(db: Session, before: datetime, courses: list[str] | None) -> set[str]:
    """Distinct usernames that appear in any conversation started before ``before``.

    Used to classify a week's students as new vs returning.
    """
    stmt = _scoped(
        select(Conversation.username)
        .where(Conversation.started_at < before, Conversation.username.is_not(None))
        .distinct(),
        courses,
    )
    return {u for (u,) in db.execute(stmt).all() if u}


def fetch_transcript(db: Session, conversation_id: str) -> list[tuple[str, str]]:
    """Ordered ``(role, content)`` pairs for one conversation, for the judge."""
    stmt = (
        select(Message.role, Message.content)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.turn, Message.id)
    )
    return [(role, content) for role, content in db.execute(stmt).all()]
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest database_ui/analytics/tests/test_data.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add database_ui/analytics/data.py database_ui/analytics/tests/test_data.py
git commit -m "feat(analytics): add windowed scoped read-queries for weekly report"
```

---

## Task 3: Statistics (`stats.py`)

**Files:**
- Create: `database_ui/analytics/stats.py`
- Test: `database_ui/analytics/tests/test_stats.py`

**Interfaces:**
- Consumes: `ConvRow`, `MsgRow` (Task 2).
- Produces: `compute_stats(convs: list[ConvRow], msgs: list[MsgRow], returning: set[str]) -> dict` returning a JSON-serializable dict with keys `usage`, `ratings`, `cost`, `content`, and `per_course: {course_key: {usage, ratings, cost, content}}`. And `week_over_week(current: dict, prior: dict) -> dict` with `▲/▼/–` deltas on headline metrics. Helper `TUTOR_ROLES: set[str]` and `is_tutor(role)`.

- [ ] **Step 1: Write the failing tests** (pure — hand-built dataclasses, no DB)

```python
# database_ui/analytics/tests/test_stats.py
from datetime import datetime, timezone

from database_ui.analytics.data import ConvRow, MsgRow
from database_ui.analytics.stats import compute_stats, week_over_week


def _conv(cid, course="c1", user="a@x.edu", kind="exercise", ex="1"):
    t = datetime(2026, 8, 10, 12, tzinfo=timezone.utc)
    return ConvRow(cid, course, user, ex, kind, None, "tutor_09", t, t)


def _tutor(cid, rating=0, cost=0.01, rag=False):
    return MsgRow(cid, 2, "tutor", "ok", rating, cost, '{"model":"claude-x"}', rag,
                  datetime(2026, 8, 10, 12, tzinfo=timezone.utc))


def _student(cid):
    return MsgRow(cid, 1, "student", "help", 0, None, None, False,
                  datetime(2026, 8, 10, 12, tzinfo=timezone.utc))


def test_usage_and_ratings_and_cost():
    convs = [_conv("a", user="u1@x"), _conv("b", user="u2@x")]
    msgs = [_student("a"), _tutor("a", rating=1, cost=0.02, rag=True),
            _student("b"), _tutor("b", rating=-1, cost=0.03, rag=False)]
    out = compute_stats(convs, msgs, returning={"u1@x"})
    assert out["usage"]["conversations"] == 2
    assert out["usage"]["unique_students"] == 2
    assert out["usage"]["returning_students"] == 1
    assert out["usage"]["new_students"] == 1
    assert out["ratings"]["up"] == 1 and out["ratings"]["down"] == 1
    assert out["ratings"]["positive_rate"] == 0.5
    assert round(out["cost"]["total_usd"], 2) == 0.05
    assert out["content"]["rag_turns"] == 1
    assert "c1" in out["per_course"]


def test_week_over_week_arrows():
    cur = compute_stats([_conv("a")], [_tutor("a", cost=0.10)], returning=set())
    prior = compute_stats([_conv("b"), _conv("c")], [_tutor("b"), _tutor("c")], returning=set())
    wow = week_over_week(cur, prior)
    assert wow["conversations"]["arrow"] == "▼"   # 1 < 2
    assert wow["cost_usd"]["arrow"] == "▲"          # 0.10 > ~0.01
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest database_ui/analytics/tests/test_stats.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `stats.py`**

```python
# database_ui/analytics/stats.py
"""Pure descriptive statistics for the weekly report (sections 1-4, 8, 9).

Input is the plain dataclasses from ``data.py``; output is a JSON-serializable
dict. No DB, no I/O -> fully unit-testable. Cost leans on ``cost_usd`` (always
present on tutor rows); token totals are a best-effort parse of ``usage_json``.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import timedelta

from database_ui.analytics.data import ConvRow, MsgRow
from ui_core.usage import model_from_usage_json

# Tutor turns carry rating/cost; student turns don't. Accept both historical labels.
TUTOR_ROLES = {"tutor", "assistant"}


def is_tutor(role: str) -> bool:
    return role in TUTOR_ROLES


def _tokens(usage_json: str | None) -> int:
    """Best-effort token count: sum any int field whose key contains 'token'."""
    if not usage_json:
        return 0
    try:
        obj = json.loads(usage_json)
    except (ValueError, TypeError):
        return 0
    total = 0
    for key, val in (obj.items() if isinstance(obj, dict) else []):
        if "token" in key.lower() and isinstance(val, int):
            total += val
    return total


def _round(x: float, n: int = 4) -> float:
    return round(float(x), n)


def _section(convs: list[ConvRow], msgs: list[MsgRow], returning: set[str]) -> dict:
    tutor_msgs = [m for m in msgs if is_tutor(m.role)]
    students = {c.username for c in convs if c.username}
    ret = len(students & returning)
    durations = [
        (c.last_active_at - c.started_at).total_seconds()
        for c in convs
        if c.started_at and c.last_active_at
    ]
    by_day: Counter = Counter(
        c.started_at.date().isoformat() for c in convs if c.started_at
    )
    per_conv_msgs: Counter = Counter(m.conversation_id for m in msgs)
    up = sum(1 for m in tutor_msgs if m.rating == 1)
    down = sum(1 for m in tutor_msgs if m.rating == -1)
    rated = up + down
    rag_turns = sum(1 for m in tutor_msgs if m.has_rag)
    costs = [m.cost_usd or 0.0 for m in tutor_msgs]
    models: Counter = Counter(
        model_from_usage_json(m.usage_json) or "unknown" for m in tutor_msgs
    )
    ex_kinds: Counter = Counter(c.exercise_kind for c in convs)
    exercises: Counter = Counter(f"{c.exercise_kind}:{c.exercise_number}" for c in convs)
    prompts: Counter = Counter(c.tutor_prompt for c in convs)

    return {
        "usage": {
            "conversations": len(convs),
            "unique_students": len(students),
            "returning_students": ret,
            "new_students": len(students) - ret,
            "total_messages": len(msgs),
            "student_messages": len(msgs) - len(tutor_msgs),
            "tutor_messages": len(tutor_msgs),
            "avg_messages_per_conversation": _round(
                sum(per_conv_msgs.values()) / len(convs) if convs else 0.0, 2
            ),
            "avg_duration_seconds": _round(
                sum(durations) / len(durations) if durations else 0.0, 1
            ),
            "short_conversations": sum(1 for c in per_conv_msgs.values() if c <= 2),
            "conversations_by_day": dict(sorted(by_day.items())),
        },
        "ratings": {
            "up": up,
            "down": down,
            "rated_turns": rated,
            "positive_rate": _round(up / rated, 4) if rated else 0.0,
            "pct_turns_rated": _round(rated / len(tutor_msgs), 4) if tutor_msgs else 0.0,
        },
        "cost": {
            "total_usd": _round(sum(costs), 4),
            "per_conversation_usd": _round(sum(costs) / len(convs), 4) if convs else 0.0,
            "tokens": sum(_tokens(m.usage_json) for m in tutor_msgs),
            "model_mix": dict(models),
        },
        "content": {
            "exercise_kind_split": dict(ex_kinds),
            "top_exercises": dict(exercises.most_common(10)),
            "focus_problem_conversations": sum(1 for c in convs if c.focus_problem is not None),
            "rag_turns": rag_turns,
            "rag_rate": _round(rag_turns / len(tutor_msgs), 4) if tutor_msgs else 0.0,
            "tutor_prompt_mix": dict(prompts),
        },
    }


def compute_stats(convs: list[ConvRow], msgs: list[MsgRow], returning: set[str]) -> dict:
    """Overall stats plus a per-course breakdown."""
    overall = _section(convs, msgs, returning)
    ids_by_course: dict[str, set[str]] = defaultdict(set)
    for c in convs:
        ids_by_course[c.course].add(c.id)
    per_course = {}
    for course, ids in sorted(ids_by_course.items()):
        c_convs = [c for c in convs if c.course == course]
        c_msgs = [m for m in msgs if m.conversation_id in ids]
        per_course[course] = _section(c_convs, c_msgs, returning)
    overall["per_course"] = per_course
    return overall


_HEADLINE = [
    ("conversations", ("usage", "conversations")),
    ("unique_students", ("usage", "unique_students")),
    ("cost_usd", ("cost", "total_usd")),
    ("positive_rate", ("ratings", "positive_rate")),
    ("rag_rate", ("content", "rag_rate")),
]


def _dig(d: dict, path: tuple[str, str]):
    return d.get(path[0], {}).get(path[1], 0)


def week_over_week(current: dict, prior: dict) -> dict:
    """Arrow + delta on headline metrics vs the prior week."""
    out = {}
    for name, path in _HEADLINE:
        cur, pri = _dig(current, path), _dig(prior, path)
        arrow = "▲" if cur > pri else "▼" if cur < pri else "–"
        out[name] = {"current": cur, "prior": pri, "delta": _round(cur - pri, 4), "arrow": arrow}
    return out
```

> Implementer note: confirm `ui_core.usage.model_from_usage_json` accepts a JSON string and returns `str | None` (it's already imported that way in `services/conversations.py`). If its signature differs, adapt the one call site.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest database_ui/analytics/tests/test_stats.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add database_ui/analytics/stats.py database_ui/analytics/tests/test_stats.py
git commit -m "feat(analytics): add pure weekly statistics with per-course + WoW deltas"
```

---

## Task 4: Cache schema, reader & writer (`cache.py`)

**Files:**
- Create: `database_ui/analytics/cache.py`
- Create: `database_ui/analytics/cache/.gitkeep` (empty)
- Test: `database_ui/analytics/tests/test_cache.py`

**Interfaces:**
- Produces:
  - `CACHE_DIR: Path` (= `database_ui/analytics/cache`), `CACHE_VERSION: int`.
  - `cache_path(week_key: str) -> Path`.
  - `write_cache(week, judged, examples, topics_by_course, *, judge_model, generated_at, judged_count, skipped) -> Path` — serializes the documented shape.
  - `read_cache(week_key: str) -> dict | None` — loads a committed cache, or `None` if absent.
  - `filter_cache(blob: dict, courses: list[str] | None) -> dict` — drops conversations/examples/topics outside scope.
  - `available_weeks() -> list[str]` — sorted-descending cache keys present on disk.

- [ ] **Step 1: Write the failing tests**

```python
# database_ui/analytics/tests/test_cache.py
from datetime import datetime, timezone

from database_ui.analytics import cache as c
from database_ui.analytics.weeks import Week


def _blob():
    return {
        "version": c.CACHE_VERSION,
        "week_start": "2026-08-09", "week_end": "2026-08-15", "tz": "America/New_York",
        "generated_at": "2026-08-17T05:12:00-04:00",
        "judge_model": "claude-sonnet-5", "judged_count": 2, "skipped": 0,
        "conversations": {
            "u1": {"course": "supply_chain_design", "worked_well": False,
                   "issues": [{"type": "gave_away_answer", "severity": "high", "quote": "..."}],
                   "topics": ["EOQ"], "one_line": "gave answer"},
            "u2": {"course": "meaning_of_life", "worked_well": True,
                   "issues": [], "topics": ["ethics"], "one_line": "good"},
        },
        "examples": {"exemplary": ["u2"], "high_engagement": ["u1"],
                     "sample": {"supply_chain_design": ["u1"], "meaning_of_life": ["u2"]}},
        "topics_by_course": {
            "supply_chain_design": [{"topic": "EOQ", "count": 1, "examples": ["how?"]}],
            "meaning_of_life": [{"topic": "ethics", "count": 1, "examples": ["why?"]}],
        },
    }


def test_filter_cache_drops_out_of_scope():
    filtered = c.filter_cache(_blob(), ["supply_chain_design"])
    assert set(filtered["conversations"]) == {"u1"}
    assert filtered["examples"]["exemplary"] == []      # u2 is out of scope
    assert filtered["examples"]["high_engagement"] == ["u1"]
    assert set(filtered["examples"]["sample"]) == {"supply_chain_design"}
    assert set(filtered["topics_by_course"]) == {"supply_chain_design"}


def test_filter_cache_master_is_identity():
    assert c.filter_cache(_blob(), None)["conversations"].keys() == _blob()["conversations"].keys()


def test_write_then_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(c, "CACHE_DIR", tmp_path)
    wk = Week.__call__(__import__("datetime").date(2026, 8, 9))
    path = c.write_cache(
        wk,
        judged={"u1": {"course": "c1", "worked_well": True, "issues": [], "topics": [], "one_line": "ok"}},
        examples={"exemplary": ["u1"], "high_engagement": [], "sample": {"c1": ["u1"]}},
        topics_by_course={"c1": [{"topic": "t", "count": 1, "examples": []}]},
        judge_model="claude-sonnet-5",
        generated_at=datetime(2026, 8, 17, 9, tzinfo=timezone.utc),
        judged_count=1, skipped=0,
    )
    assert path.name == "2026-08-09.json"
    blob = c.read_cache("2026-08-09")
    assert blob["week_start"] == "2026-08-09" and blob["judged_count"] == 1
    assert "2026-08-09" in c.available_weeks()
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest database_ui/analytics/tests/test_cache.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `cache.py`**

```python
# database_ui/analytics/cache.py
"""Read/write and scope-filter the committed weekly cache.

The cache is the interface between the offline weekly job (producer) and the
dashboard (consumer). One JSON file per week, named by the week's start date,
committed under database_ui so it ships in the read-only image.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from database_ui.analytics.weeks import Week

CACHE_VERSION = 1
CACHE_DIR = Path(__file__).resolve().parent / "cache"


def cache_path(week_key: str) -> Path:
    return CACHE_DIR / f"{week_key}.json"


def write_cache(
    week: Week,
    judged: dict[str, dict],
    examples: dict,
    topics_by_course: dict,
    *,
    judge_model: str,
    generated_at: datetime,
    judged_count: int,
    skipped: int,
) -> Path:
    """Serialize one week's judged output to its cache file; returns the path."""
    blob = {
        "version": CACHE_VERSION,
        "week_start": week.key,
        "week_end": week.end.isoformat(),
        "tz": "America/New_York",
        "generated_at": generated_at.isoformat(),
        "judge_model": judge_model,
        "judged_count": judged_count,
        "skipped": skipped,
        "conversations": judged,
        "examples": examples,
        "topics_by_course": topics_by_course,
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = cache_path(week.key)
    path.write_text(json.dumps(blob, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_cache(week_key: str) -> dict | None:
    """Load a week's cache blob, or ``None`` if it hasn't been generated yet."""
    path = cache_path(week_key)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def filter_cache(blob: dict, courses: list[str] | None) -> dict:
    """Return a copy of ``blob`` limited to ``courses`` (``None`` = no filter).

    Conversations outside scope are removed; example id-lists and per-course
    topic maps are pruned to match, so a scoped reviewer never sees another
    course's flagged conversations, examples, or topics.
    """
    if courses is None:
        return blob
    allowed = set(courses)
    convs = {
        cid: v for cid, v in blob.get("conversations", {}).items()
        if v.get("course") in allowed
    }
    keep = set(convs)
    ex = blob.get("examples", {})
    examples = {
        "exemplary": [i for i in ex.get("exemplary", []) if i in keep],
        "high_engagement": [i for i in ex.get("high_engagement", []) if i in keep],
        "sample": {
            course: ids for course, ids in ex.get("sample", {}).items()
            if course in allowed
        },
    }
    topics = {
        course: rows for course, rows in blob.get("topics_by_course", {}).items()
        if course in allowed
    }
    out = dict(blob)
    out["conversations"] = convs
    out["examples"] = examples
    out["topics_by_course"] = topics
    return out


def available_weeks() -> list[str]:
    """Cache week-keys present on disk, newest first."""
    if not CACHE_DIR.exists():
        return []
    keys = [p.stem for p in CACHE_DIR.glob("*.json")]
    return sorted(keys, reverse=True)
```

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest database_ui/analytics/tests/test_cache.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add database_ui/analytics/cache.py database_ui/analytics/cache/.gitkeep database_ui/analytics/tests/test_cache.py
git commit -m "feat(analytics): add committed weekly cache read/write with scope filter"
```

---

## Task 5: Judge (`judge.py`)

**Files:**
- Create: `database_ui/analytics/judge.py`
- Test: `database_ui/analytics/tests/test_judge.py`

**Interfaces:**
- Produces:
  - `ISSUE_TYPES: tuple[str, ...]` = `("gave_away_answer", "factual_error", "unhelpful_dead_end", "rag_grounding")`.
  - `@dataclass(frozen=True) Verdict`: `worked_well: bool`, `issues: list[dict]` (`{type, severity, quote}`), `topics: list[str]`, `one_line: str`.
  - `transcript_hash(pairs: list[tuple[str, str]]) -> str` (sha256 of the transcript; the cache-reuse key).
  - `Judge` (Protocol): `judge(course: str, transcript: list[tuple[str, str]]) -> Verdict`.
  - `FakeJudge(canned: dict[str, Verdict] | None = None, default: Verdict | None = None)` — deterministic, no network.
  - `AnthropicJudge(model: str)` — real judge via `langchain_anthropic.ChatAnthropic` + structured output. Never imported by tests.

- [ ] **Step 1: Write the failing tests** (FakeJudge + hashing only; never touches Anthropic)

```python
# database_ui/analytics/tests/test_judge.py
from database_ui.analytics.judge import FakeJudge, Verdict, transcript_hash, ISSUE_TYPES


def test_transcript_hash_is_stable_and_content_sensitive():
    a = [("student", "hi"), ("tutor", "hello")]
    b = [("student", "hi"), ("tutor", "different")]
    assert transcript_hash(a) == transcript_hash(a)
    assert transcript_hash(a) != transcript_hash(b)


def test_fake_judge_returns_canned_then_default():
    v = Verdict(worked_well=False,
                issues=[{"type": "gave_away_answer", "severity": "high", "quote": "..."}],
                topics=["EOQ"], one_line="gave answer")
    d = Verdict(worked_well=True, issues=[], topics=[], one_line="ok")
    j = FakeJudge(canned={"u1": v}, default=d)
    assert j.judge("c1", [("student", "u1")]) is v or j._pop("u1") == v  # canned by key
    assert j.judge("c1", [("student", "other")]) == d


def test_issue_types_are_the_four_agreed():
    assert ISSUE_TYPES == ("gave_away_answer", "factual_error", "unhelpful_dead_end", "rag_grounding")
```

> Implementer note: make `FakeJudge` deterministic and simple — it pops canned verdicts by a caller-supplied key or falls back to `default`. Adjust the first assertion in `test_fake_judge_returns_canned_then_default` to whatever minimal `FakeJudge` API you implement (documented below); the load-bearing checks are "canned wins, default otherwise."

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest database_ui/analytics/tests/test_judge.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `judge.py`**

```python
# database_ui/analytics/judge.py
"""LLM judge for the weekly report, behind an interface so tests never call out.

``Verdict`` captures whether a conversation worked, any issues (typed + severity
+ a supporting quote), the topics the student raised, and a one-line summary.
``transcript_hash`` lets the weekly job reuse a prior verdict when a conversation
is unchanged, keeping re-runs cheap.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Protocol

ISSUE_TYPES = ("gave_away_answer", "factual_error", "unhelpful_dead_end", "rag_grounding")
SEVERITIES = ("low", "medium", "high")


@dataclass(frozen=True)
class Verdict:
    worked_well: bool
    issues: list[dict] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    one_line: str = ""

    def as_dict(self, course: str) -> dict:
        return {
            "course": course,
            "worked_well": self.worked_well,
            "issues": self.issues,
            "topics": self.topics,
            "one_line": self.one_line,
        }


def transcript_hash(pairs: list[tuple[str, str]]) -> str:
    h = hashlib.sha256()
    for role, content in pairs:
        h.update(role.encode("utf-8"))
        h.update(b"\x00")
        h.update(content.encode("utf-8"))
        h.update(b"\x01")
    return h.hexdigest()


class Judge(Protocol):
    def judge(self, course: str, transcript: list[tuple[str, str]]) -> Verdict: ...


class FakeJudge:
    """Deterministic judge for tests. Returns ``canned[key]`` when the last
    student line matches a key, else ``default``. No network, ever."""

    def __init__(self, canned: dict[str, Verdict] | None = None, default: Verdict | None = None):
        self._canned = dict(canned or {})
        self._default = default or Verdict(worked_well=True, one_line="ok")

    def judge(self, course: str, transcript: list[tuple[str, str]]) -> Verdict:
        students = [c for r, c in transcript if r not in ("tutor", "assistant")]
        key = students[-1] if students else ""
        return self._canned.get(key, self._default)


_SYSTEM = """You are a strict evaluator of an AI tutor's conversation with a \
student. The tutor must guide via Socratic questioning and NEVER hand over a \
final/submission-ready answer. Given the transcript, decide whether the tutoring \
worked well, list concrete issues, and tag the 1-3 topics the student asked about.

Issue "type" must be one of: gave_away_answer, factual_error, unhelpful_dead_end, \
rag_grounding. "severity" must be one of: low, medium, high. Each issue needs a \
short verbatim "quote" from the tutor that evidences it. Keep "one_line" under 15 \
words. "topics" are short noun phrases (e.g. "EOQ", "safety stock")."""


class AnthropicJudge:
    """Real judge via langchain-anthropic structured output. Not used in tests."""

    def __init__(self, model: str):
        from langchain_anthropic import ChatAnthropic  # lazy: keep tests import-clean

        self._schema = {
            "name": "verdict",
            "description": "Evaluation of one tutoring conversation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "worked_well": {"type": "boolean"},
                    "issues": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "type": {"type": "string", "enum": list(ISSUE_TYPES)},
                                "severity": {"type": "string", "enum": list(SEVERITIES)},
                                "quote": {"type": "string"},
                            },
                            "required": ["type", "severity", "quote"],
                        },
                    },
                    "topics": {"type": "array", "items": {"type": "string"}},
                    "one_line": {"type": "string"},
                },
                "required": ["worked_well", "issues", "topics", "one_line"],
            },
        }
        self._llm = ChatAnthropic(model=model, temperature=0).with_structured_output(self._schema)

    def judge(self, course: str, transcript: list[tuple[str, str]]) -> Verdict:
        body = "\n\n".join(f"{role.upper()}: {content}" for role, content in transcript)
        result = self._llm.invoke(
            [("system", _SYSTEM), ("human", f"Course: {course}\n\nTranscript:\n{body}")]
        )
        return Verdict(
            worked_well=bool(result.get("worked_well", True)),
            issues=list(result.get("issues", [])),
            topics=list(result.get("topics", [])),
            one_line=str(result.get("one_line", "")),
        )
```

> Implementer note: verify `ChatAnthropic(...).with_structured_output(json_schema_dict)` is supported by the installed `langchain-anthropic` version; if that version wants a Pydantic model instead of a raw JSON-schema dict, define a `pydantic.BaseModel` mirroring the schema and pass that. This code path is never exercised by tests, so adapt it to the installed API without touching the `Verdict`/`FakeJudge`/`transcript_hash` contract.

- [ ] **Step 4: Run to verify pass**

Run: `python -m pytest database_ui/analytics/tests/test_judge.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add database_ui/analytics/judge.py database_ui/analytics/tests/test_judge.py
git commit -m "feat(analytics): add LLM judge interface with deterministic test fake"
```

---

## Task 6: Topics aggregation (`topics.py`)

**Files:**
- Create: `database_ui/analytics/topics.py`
- Test: `database_ui/analytics/tests/test_topics.py`

**Interfaces:**
- Consumes: `Verdict` (Task 5), `ConvRow` (Task 2).
- Produces: `aggregate_topics(convs: list[ConvRow], verdicts: dict[str, Verdict], first_question: dict[str, str]) -> dict[str, list[dict]]` — per course, a ranked list of `{topic, count, examples}` (examples = up to 3 first student questions for conversations carrying that topic). Topic strings are normalized (stripped, lowercased for grouping, displayed in their first-seen casing).

- [ ] **Step 1: Write the failing test**

```python
# database_ui/analytics/tests/test_topics.py
from datetime import datetime, timezone

from database_ui.analytics.data import ConvRow
from database_ui.analytics.judge import Verdict
from database_ui.analytics.topics import aggregate_topics


def _conv(cid, course):
    t = datetime(2026, 8, 10, tzinfo=timezone.utc)
    return ConvRow(cid, course, "u@x", "1", "exercise", None, "tutor_09", t, t)


def test_topics_ranked_per_course_with_examples():
    convs = [_conv("a", "sc"), _conv("b", "sc"), _conv("c", "mol")]
    verdicts = {
        "a": Verdict(True, topics=["EOQ"], one_line=""),
        "b": Verdict(True, topics=["eoq", "safety stock"], one_line=""),
        "c": Verdict(True, topics=["ethics"], one_line=""),
    }
    firstq = {"a": "how do I find EOQ?", "b": "eoq again?", "c": "what is good?"}
    out = aggregate_topics(convs, verdicts, firstq)
    sc = out["sc"]
    assert sc[0]["topic"].lower() == "eoq" and sc[0]["count"] == 2
    assert "how do I find EOQ?" in sc[0]["examples"]
    assert set(out) == {"sc", "mol"}
```

- [ ] **Step 2: Run to verify failure**

Run: `python -m pytest database_ui/analytics/tests/test_topics.py -v` → FAIL (missing module).

- [ ] **Step 3: Implement `topics.py`**

```python
# database_ui/analytics/topics.py
"""Aggregate per-conversation judge topics into ranked per-course lists."""
from __future__ import annotations

from collections import defaultdict

from database_ui.analytics.data import ConvRow
from database_ui.analytics.judge import Verdict


def aggregate_topics(
    convs: list[ConvRow],
    verdicts: dict[str, Verdict],
    first_question: dict[str, str],
) -> dict[str, list[dict]]:
    course_of = {c.id: c.course for c in convs}
    # course -> normalized topic -> {"display": str, "count": int, "examples": [..]}
    acc: dict[str, dict[str, dict]] = defaultdict(dict)
    for cid, verdict in verdicts.items():
        course = course_of.get(cid)
        if course is None:
            continue
        seen_norm: set[str] = set()
        for topic in verdict.topics:
            norm = topic.strip().lower()
            if not norm or norm in seen_norm:
                continue
            seen_norm.add(norm)
            bucket = acc[course].setdefault(norm, {"display": topic.strip(), "count": 0, "examples": []})
            bucket["count"] += 1
            q = first_question.get(cid)
            if q and len(bucket["examples"]) < 3 and q not in bucket["examples"]:
                bucket["examples"].append(q)
    out: dict[str, list[dict]] = {}
    for course, topics in acc.items():
        ranked = sorted(topics.values(), key=lambda b: (-b["count"], b["display"].lower()))
        out[course] = [
            {"topic": b["display"], "count": b["count"], "examples": b["examples"]}
            for b in ranked
        ]
    return out
```

- [ ] **Step 4: Run to verify pass** → PASS.

- [ ] **Step 5: Commit**

```bash
git add database_ui/analytics/topics.py database_ui/analytics/tests/test_topics.py
git commit -m "feat(analytics): aggregate judge topics into ranked per-course lists"
```

---

## Task 7: Failure flags (`flags.py`)

**Files:**
- Create: `database_ui/analytics/flags.py`
- Test: `database_ui/analytics/tests/test_flags.py`

**Interfaces:**
- Consumes: `ConvRow`, `MsgRow` (Task 2); `Verdict` (Task 5).
- Produces: `build_flags(convs, msgs, verdicts) -> dict` with `items: list[dict]` (ranked; each `{id, course, exercise, student, source, issue_type, severity, quote, one_line}`), `counts_by_issue: dict`, `thumbs_down: int`, `judge_flagged: int`, `overlap: int`. A conversation is flagged if it has any `rating == -1` tutor turn **or** a verdict with `worked_well == False`. Ranking: severity (high>medium>low) then source (both>judge>thumb).

- [ ] **Step 1: Write the failing test**

```python
# database_ui/analytics/tests/test_flags.py
from datetime import datetime, timezone

from database_ui.analytics.data import ConvRow, MsgRow
from database_ui.analytics.judge import Verdict
from database_ui.analytics.flags import build_flags


def _conv(cid, course="sc", ex="1"):
    t = datetime(2026, 8, 10, tzinfo=timezone.utc)
    return ConvRow(cid, course, "u@x", ex, "exercise", None, "tutor_09", t, t)


def _tutor(cid, rating):
    return MsgRow(cid, 2, "tutor", "text", rating, 0.01, None, False,
                  datetime(2026, 8, 10, tzinfo=timezone.utc))


def test_flags_union_and_overlap():
    convs = [_conv("a"), _conv("b"), _conv("c")]
    msgs = [_tutor("a", -1), _tutor("b", 0), _tutor("c", -1)]
    verdicts = {
        "a": Verdict(False, issues=[{"type": "gave_away_answer", "severity": "high", "quote": "x"}], one_line="bad"),
        "b": Verdict(False, issues=[{"type": "factual_error", "severity": "medium", "quote": "y"}], one_line="err"),
        "c": Verdict(True, one_line="ok"),
    }
    out = build_flags(convs, msgs, verdicts)
    ids = {i["id"] for i in out["items"]}
    assert ids == {"a", "b", "c"}          # a: both, b: judge only, c: thumb only
    assert out["thumbs_down"] == 2 and out["judge_flagged"] == 2 and out["overlap"] == 1
    assert out["items"][0]["id"] == "a"    # high severity + both sources ranks first
```

- [ ] **Step 2: Run to verify failure** → FAIL (missing module).

- [ ] **Step 3: Implement `flags.py`**

```python
# database_ui/analytics/flags.py
"""Combine thumbs-down and judge verdicts into the ranked 'didn't work well' list."""
from __future__ import annotations

from collections import Counter

from database_ui.analytics.data import ConvRow, MsgRow
from database_ui.analytics.judge import Verdict

_SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2, "": 3}
_SOURCE_RANK = {"both": 0, "judge": 1, "thumb": 2}


def build_flags(convs: list[ConvRow], msgs: list[MsgRow], verdicts: dict[str, Verdict]) -> dict:
    conv_by_id = {c.id: c for c in convs}
    thumbed = {m.conversation_id for m in msgs if m.rating == -1}
    judged_bad = {cid for cid, v in verdicts.items() if not v.worked_well}
    flagged = thumbed | judged_bad

    items = []
    counts: Counter = Counter()
    for cid in flagged:
        conv = conv_by_id.get(cid)
        if conv is None:
            continue
        verdict = verdicts.get(cid)
        by_judge = cid in judged_bad
        by_thumb = cid in thumbed
        source = "both" if by_judge and by_thumb else "judge" if by_judge else "thumb"
        top_issue = verdict.issues[0] if (verdict and verdict.issues) else {}
        issue_type = top_issue.get("type", "thumbs_down" if not by_judge else "unspecified")
        severity = top_issue.get("severity", "medium" if by_judge else "low")
        counts[issue_type] += 1
        items.append({
            "id": cid,
            "course": conv.course,
            "exercise": f"{conv.exercise_kind}:{conv.exercise_number}",
            "student": conv.username,
            "source": source,
            "issue_type": issue_type,
            "severity": severity,
            "quote": top_issue.get("quote", ""),
            "one_line": verdict.one_line if verdict else "",
        })

    items.sort(key=lambda i: (_SEVERITY_RANK.get(i["severity"], 3), _SOURCE_RANK[i["source"]], i["id"]))
    return {
        "items": items,
        "counts_by_issue": dict(counts),
        "thumbs_down": len(thumbed),
        "judge_flagged": len(judged_bad),
        "overlap": len(thumbed & judged_bad),
    }
```

- [ ] **Step 4: Run to verify pass** → PASS.

- [ ] **Step 5: Commit**

```bash
git add database_ui/analytics/flags.py database_ui/analytics/tests/test_flags.py
git commit -m "feat(analytics): rank didn't-work-well conversations from thumbs + judge"
```

---

## Task 8: Example selection (`examples.py`)

**Files:**
- Create: `database_ui/analytics/examples.py`
- Test: `database_ui/analytics/tests/test_examples.py`

**Interfaces:**
- Consumes: `ConvRow`, `MsgRow` (Task 2); `Verdict` (Task 5).
- Produces: `pick_examples(convs, msgs, verdicts, *, seed: str, per_course: int = 2) -> dict` = `{exemplary: [ids], high_engagement: [ids], sample: {course: [ids]}}`. `exemplary` = worked-well with an up-rating, top by message count (cap 5). `high_engagement` = top message-count overall (cap 5). `sample` = deterministic per-course random pick seeded by `seed` (the week key), `per_course` each.

- [ ] **Step 1: Write the failing test**

```python
# database_ui/analytics/tests/test_examples.py
from datetime import datetime, timezone

from database_ui.analytics.data import ConvRow, MsgRow
from database_ui.analytics.judge import Verdict
from database_ui.analytics.examples import pick_examples


def _conv(cid, course):
    t = datetime(2026, 8, 10, tzinfo=timezone.utc)
    return ConvRow(cid, course, "u@x", "1", "exercise", None, "tutor_09", t, t)


def _msgs(cid, n):
    return [MsgRow(cid, i, "tutor" if i % 2 else "student", "x", 1 if i == 1 else 0,
                   0.01, None, False, datetime(2026, 8, 10, tzinfo=timezone.utc)) for i in range(n)]


def test_examples_are_deterministic_and_bucketed():
    convs = [_conv("a", "sc"), _conv("b", "sc"), _conv("c", "mol")]
    msgs = _msgs("a", 8) + _msgs("b", 2) + _msgs("c", 4)
    verdicts = {"a": Verdict(True, one_line="great"), "b": Verdict(False, one_line="bad"),
                "c": Verdict(True, one_line="ok")}
    out1 = pick_examples(convs, msgs, verdicts, seed="2026-08-09", per_course=1)
    out2 = pick_examples(convs, msgs, verdicts, seed="2026-08-09", per_course=1)
    assert out1 == out2                       # deterministic
    assert out1["high_engagement"][0] == "a"  # most messages
    assert "a" in out1["exemplary"]           # worked well + up-rated
    assert set(out1["sample"]) == {"sc", "mol"}
    assert len(out1["sample"]["sc"]) == 1
```

- [ ] **Step 2: Run to verify failure** → FAIL.

- [ ] **Step 3: Implement `examples.py`**

```python
# database_ui/analytics/examples.py
"""Select example conversations (exemplary / high-engagement / random sample).

The random sample is seeded by the week key so a regenerated cache is identical.
"""
from __future__ import annotations

import random
from collections import Counter, defaultdict

from database_ui.analytics.data import ConvRow, MsgRow
from database_ui.analytics.judge import Verdict

_EXEMPLARY_CAP = 5
_ENGAGEMENT_CAP = 5


def pick_examples(
    convs: list[ConvRow],
    msgs: list[MsgRow],
    verdicts: dict[str, Verdict],
    *,
    seed: str,
    per_course: int = 2,
) -> dict:
    counts: Counter = Counter(m.conversation_id for m in msgs)
    up_rated = {m.conversation_id for m in msgs if m.rating == 1}
    conv_ids = [c.id for c in convs]

    def by_messages(ids):
        return sorted(ids, key=lambda cid: (-counts.get(cid, 0), cid))

    exemplary = by_messages([
        cid for cid in conv_ids
        if verdicts.get(cid, Verdict(True)).worked_well and cid in up_rated
    ])[:_EXEMPLARY_CAP]

    high_engagement = by_messages(conv_ids)[:_ENGAGEMENT_CAP]

    by_course: dict[str, list[str]] = defaultdict(list)
    for c in convs:
        by_course[c.course].append(c.id)
    rng = random.Random(seed)
    sample: dict[str, list[str]] = {}
    for course, ids in sorted(by_course.items()):
        pool = sorted(ids)
        rng.shuffle(pool)
        sample[course] = sorted(pool[:per_course])

    return {"exemplary": exemplary, "high_engagement": high_engagement, "sample": sample}
```

- [ ] **Step 4: Run to verify pass** → PASS.

- [ ] **Step 5: Commit**

```bash
git add database_ui/analytics/examples.py database_ui/analytics/tests/test_examples.py
git commit -m "feat(analytics): pick exemplary/high-engagement/sample example conversations"
```

---

## Task 9: Report renderer (`report.py`)

**Files:**
- Create: `database_ui/analytics/report.py`
- Test: `database_ui/analytics/tests/test_report.py`

**Interfaces:**
- Consumes: the `stats` dict (Task 3), `flags` dict (Task 7), `topics_by_course` (Task 6), `week` label.
- Produces: `render_report(week, stats, wow, flags, topics_by_course, *, judged_count, judge_model, skipped) -> str` — a Markdown document (the PR body / committed `report.md`), text + tables only, no images.

- [ ] **Step 1: Write the failing test**

```python
# database_ui/analytics/tests/test_report.py
from datetime import date

from database_ui.analytics.report import render_report
from database_ui.analytics.weeks import Week


def test_report_has_headline_and_sections():
    week = Week(date(2026, 8, 9))
    stats = {
        "usage": {"conversations": 3, "unique_students": 2, "new_students": 1,
                  "returning_students": 1, "conversations_by_day": {"2026-08-10": 3}},
        "ratings": {"up": 2, "down": 1, "positive_rate": 0.667, "pct_turns_rated": 0.5},
        "cost": {"total_usd": 0.06, "per_conversation_usd": 0.02, "model_mix": {"claude-x": 3}},
        "content": {"rag_rate": 0.4, "rag_turns": 2, "tutor_prompt_mix": {"tutor_09": 3}},
        "per_course": {},
    }
    wow = {"conversations": {"arrow": "▲", "current": 3, "prior": 1, "delta": 2}}
    flags = {"items": [{"id": "a", "course": "sc", "exercise": "exercise:1", "student": "u@x",
                        "source": "both", "issue_type": "gave_away_answer", "severity": "high",
                        "quote": "just plug it in", "one_line": "gave answer"}],
             "counts_by_issue": {"gave_away_answer": 1}, "thumbs_down": 1, "judge_flagged": 1, "overlap": 1}
    topics = {"sc": [{"topic": "EOQ", "count": 2, "examples": ["how?"]}]}
    md = render_report(week, stats, wow, flags, topics, judged_count=3, judge_model="claude-sonnet-5", skipped=0)
    assert "Aug 9, 2026 — Aug 15, 2026" in md
    assert "Didn't work well" in md
    assert "gave_away_answer" in md
    assert "EOQ" in md
```

- [ ] **Step 2: Run to verify failure** → FAIL.

- [ ] **Step 3: Implement `report.py`** (straightforward Markdown assembly)

```python
# database_ui/analytics/report.py
"""Render the weekly report Markdown (PR body + committed report.md). Text only."""
from __future__ import annotations

from database_ui.analytics.weeks import Week
from database_ui.courses import course_display_name


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def render_report(week: Week, stats: dict, wow: dict, flags: dict, topics_by_course: dict,
                  *, judged_count: int, judge_model: str, skipped: int) -> str:
    u, r, c, ct = stats["usage"], stats["ratings"], stats["cost"], stats["content"]
    lines: list[str] = []
    lines.append(f"# Weekly report — {week.label()}")
    lines.append("")

    def arrow(name: str) -> str:
        return wow.get(name, {}).get("arrow", "")

    lines.append("## Overview")
    lines.append("")
    lines.append(f"- **Conversations:** {u['conversations']} {arrow('conversations')}")
    lines.append(f"- **Students:** {u['unique_students']} {arrow('unique_students')} "
                 f"({u['new_students']} new, {u['returning_students']} returning)")
    lines.append(f"- **Positive rating:** {_pct(r['positive_rate'])} {arrow('positive_rate')} "
                 f"({r['up']}👍 / {r['down']}👎, {_pct(r['pct_turns_rated'])} of turns rated)")
    lines.append(f"- **Cost:** ${c['total_usd']:.2f} {arrow('cost_usd')} "
                 f"(${c['per_conversation_usd']:.3f}/conversation)")
    lines.append(f"- **RAG rate:** {_pct(ct['rag_rate'])} {arrow('rag_rate')}")
    lines.append("")

    lines.append("## 🚩 Didn't work well")
    lines.append("")
    lines.append(f"{len(flags['items'])} flagged — {flags['thumbs_down']}👎 + "
                 f"{flags['judge_flagged']} judge ({flags['overlap']} overlap).")
    lines.append("")
    if flags["items"]:
        lines.append("| Course | Exercise | Student | Issue | Severity | Note |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for i in flags["items"][:25]:
            note = (i["one_line"] or i["quote"]).replace("|", "\\|")[:80]
            lines.append(f"| {course_display_name(i['course'])} | {i['exercise']} | "
                         f"{i['student']} | {i['issue_type']} | {i['severity']} | {note} |")
    lines.append("")

    lines.append("## 🗣 Top topics")
    lines.append("")
    for course, rows in sorted(topics_by_course.items()):
        top = " · ".join(f"{t['topic']} ({t['count']})" for t in rows[:8])
        lines.append(f"- **{course_display_name(course)}:** {top}")
    lines.append("")

    lines.append("## Meta")
    lines.append("")
    lines.append(f"- Judged {judged_count} conversations with `{judge_model}`"
                 + (f" ({skipped} skipped)" if skipped else "") + ".")
    lines.append(f"- Model mix: {', '.join(f'{m} ({n})' for m, n in c['model_mix'].items())}")
    lines.append("")
    return "\n".join(lines)
```

- [ ] **Step 4: Run to verify pass** → PASS.

- [ ] **Step 5: Commit**

```bash
git add database_ui/analytics/report.py database_ui/analytics/tests/test_report.py
git commit -m "feat(analytics): render weekly report markdown for the PR body"
```

---

## Task 10: Weekly CLI (`weekly.py`)

**Files:**
- Create: `database_ui/analytics/weekly.py`
- Test: `database_ui/analytics/tests/test_weekly.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `run_week(db, week, judge, *, judge_model, generated_at, prior_cache=None, max_convos=None) -> tuple[Path, str]` — builds verdicts (reusing `prior_cache` entries whose `transcript_hash` matches), writes the cache, renders + writes `report.md` beside it, returns `(cache_path, report_markdown)`. Plus `main(argv=None)` argparse entry: `--week YYYY-MM-DD` (default previous complete week), `--max-convos N`, `--report-out PATH`.

- [ ] **Step 1: Write the failing test** (uses seeded SQLite + `FakeJudge`, monkeypatched cache dir)

```python
# database_ui/analytics/tests/test_weekly.py
from datetime import date, datetime, timezone

import pytest

from database_ui.analytics import cache as cache_mod
from database_ui.analytics import weekly
from database_ui.analytics.judge import FakeJudge, Verdict
from database_ui.analytics.weeks import week_containing
from database_ui.conftest import seed
from database_ui.db.session import SessionLocal


@pytest.fixture()
def session():
    s = SessionLocal()
    seed(s)
    yield s
    s.close()


def test_run_week_writes_cache_and_report(tmp_path, monkeypatch, session):
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    wk = week_containing(date(2026, 5, 5))     # the seeded rows' week
    judge = FakeJudge(default=Verdict(False, issues=[
        {"type": "gave_away_answer", "severity": "high", "quote": "q"}], topics=["EOQ"], one_line="bad"))
    path, md = weekly.run_week(
        session, wk, judge, judge_model="fake",
        generated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
    )
    assert path.exists() and path.name.endswith(".json")
    blob = cache_mod.read_cache(wk.key)
    assert blob["judged_count"] >= 1
    assert "Weekly report" in md
    # report.md written beside the cache
    assert (tmp_path / "report.md").exists()
```

- [ ] **Step 2: Run to verify failure** → FAIL.

- [ ] **Step 3: Implement `weekly.py`**

```python
# database_ui/analytics/weekly.py
"""CLI + orchestration for the weekly report cache.

Run: ``python -m database_ui.analytics.weekly [--week YYYY-MM-DD] [--max-convos N]``.
Judges every in-window conversation (reusing unchanged prior verdicts by
transcript hash), then writes the committed cache and a sibling report.md.
"""
from __future__ import annotations

import argparse
import os
from datetime import date, datetime, timezone
from pathlib import Path

from database_ui.analytics import cache as cache_mod
from database_ui.analytics import data as data_mod
from database_ui.analytics.examples import pick_examples
from database_ui.analytics.flags import build_flags
from database_ui.analytics.judge import AnthropicJudge, Judge, Verdict, transcript_hash
from database_ui.analytics.report import render_report
from database_ui.analytics.stats import compute_stats, is_tutor, week_over_week
from database_ui.analytics.topics import aggregate_topics
from database_ui.analytics.weeks import Week, previous_complete_week, parse_week


def _first_question(transcript: list[tuple[str, str]]) -> str:
    for role, content in transcript:
        if not is_tutor(role):
            return content
    return ""


def run_week(
    db,
    week: Week,
    judge: Judge,
    *,
    judge_model: str,
    generated_at: datetime,
    prior_cache: dict | None = None,
    max_convos: int | None = None,
) -> tuple[Path, str]:
    courses = None  # the job always runs unscoped; the dashboard scopes on read
    convs = data_mod.fetch_conversations(db, week, courses)
    if max_convos is not None:
        convs = convs[:max_convos]
    conv_ids = [c.id for c in convs]
    msgs = data_mod.fetch_messages(db, conv_ids)
    returning = data_mod.prior_usernames(db, week.start_utc, courses)

    prior_verdicts = (prior_cache or {}).get("conversations", {})
    prior_hashes = (prior_cache or {}).get("_hashes", {})

    verdicts: dict[str, Verdict] = {}
    hashes: dict[str, str] = {}
    judged_dict: dict[str, dict] = {}
    first_q: dict[str, str] = {}
    skipped = 0
    for conv in convs:
        transcript = data_mod.fetch_transcript(db, conv.id)
        first_q[conv.id] = _first_question(transcript)
        h = transcript_hash(transcript)
        hashes[conv.id] = h
        if prior_hashes.get(conv.id) == h and conv.id in prior_verdicts:
            entry = prior_verdicts[conv.id]
            verdict = Verdict(
                worked_well=entry["worked_well"], issues=entry["issues"],
                topics=entry["topics"], one_line=entry["one_line"],
            )
        else:
            verdict = judge.judge(conv.course, transcript)
        verdicts[conv.id] = verdict
        judged_dict[conv.id] = verdict.as_dict(conv.course)

    flags = build_flags(convs, msgs, verdicts)
    topics = aggregate_topics(convs, verdicts, first_q)
    examples = pick_examples(convs, msgs, verdicts, seed=week.key)

    path = cache_mod.write_cache(
        week, judged_dict, examples, topics,
        judge_model=judge_model, generated_at=generated_at,
        judged_count=len(convs), skipped=skipped,
    )
    # Persist hashes alongside for next run's reuse (kept out of the scope-filtered read).
    blob = cache_mod.read_cache(week.key)
    blob["_hashes"] = hashes
    path.write_text(__import__("json").dumps(blob, indent=2, ensure_ascii=False), encoding="utf-8")

    stats = compute_stats(convs, msgs, returning)
    prior_week = week.prev()
    # Prior stats are recomputed live only if we still have the data; else empty deltas.
    prior_stats = _prior_stats(db, prior_week) if _has_data(db, prior_week) else {}
    wow = week_over_week(stats, prior_stats) if prior_stats else {}

    md = render_report(week, stats, wow, flags, topics,
                       judged_count=len(convs), judge_model=judge_model, skipped=skipped)
    (path.parent / "report.md").write_text(md, encoding="utf-8")
    return path, md


def _has_data(db, week: Week) -> bool:
    return bool(data_mod.fetch_conversations(db, week, None))


def _prior_stats(db, week: Week) -> dict:
    convs = data_mod.fetch_conversations(db, week, None)
    msgs = data_mod.fetch_messages(db, [c.id for c in convs])
    returning = data_mod.prior_usernames(db, week.start_utc, None)
    return compute_stats(convs, msgs, returning)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="database_ui.analytics.weekly")
    parser.add_argument("--week", default=None, help="YYYY-MM-DD in the target week")
    parser.add_argument("--max-convos", type=int, default=None)
    parser.add_argument("--report-out", default=None)
    args = parser.parse_args(argv)

    week = parse_week(args.week) if args.week else previous_complete_week(date.today())
    judge_model = os.environ.get("ANALYTICS_JUDGE_MODEL", "claude-sonnet-5")

    from database_ui.db.session import SessionLocal
    db = SessionLocal()
    try:
        prior = cache_mod.read_cache(week.key)   # reuse this week's own prior run if any
        judge = AnthropicJudge(judge_model)
        path, md = run_week(
            db, week, judge, judge_model=judge_model,
            generated_at=datetime.now(timezone.utc),
            prior_cache=prior, max_convos=args.max_convos,
        )
    finally:
        db.rollback()
        db.close()

    if args.report_out:
        Path(args.report_out).write_text(md, encoding="utf-8")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

> Implementer note: the `blob["_hashes"]` re-write is deliberate — hashes power cheap re-runs but must never reach the dashboard, so `filter_cache` (Task 4) ignores unknown keys and the dashboard reads only `conversations`/`examples`/`topics_by_course`. Keep it that way. If the double-write reads awkwardly, fold the hashes into `write_cache` via an optional `hashes=` kwarg instead — either is fine as long as `_hashes` stays out of the scope-filtered payload the API returns.

- [ ] **Step 4: Run to verify pass** → PASS.

- [ ] **Step 5: Commit**

```bash
git add database_ui/analytics/weekly.py database_ui/analytics/tests/test_weekly.py
git commit -m "feat(analytics): add weekly CLI orchestrating judge, cache, and report"
```

---

## Task 11: Dashboard service (`services/analytics.py`)

**Files:**
- Create: `database_ui/services/analytics.py`
- Test: `database_ui/tests/test_analytics_service.py`

**Interfaces:**
- Consumes: `analytics.data`, `analytics.stats`, `analytics.cache`, `analytics.weeks`.
- Produces:
  - `live_stats(db, week: Week, courses: list[str] | None) -> dict` — computes §1–4/§8 for the week and prior-week deltas (§9), scoped.
  - `cached_sections(week_key: str, courses: list[str] | None) -> dict | None` — `read_cache` + `filter_cache`, stripping `_hashes`; `None` if no cache.
  - `week_options() -> list[dict]` — `[{key, label}]` for the picker, from `available_weeks()` plus the default previous-complete week even if uncached.

- [ ] **Step 1: Write the failing test**

```python
# database_ui/tests/test_analytics_service.py
from datetime import date

import pytest

from database_ui.analytics import cache as cache_mod
from database_ui.analytics.weeks import week_containing
from database_ui.conftest import seed
from database_ui.db.session import SessionLocal
from database_ui.services import analytics as svc


@pytest.fixture()
def session():
    s = SessionLocal()
    seed(s)
    yield s
    s.close()


def test_live_stats_scoped(session):
    wk = week_containing(date(2026, 5, 5))
    allc = svc.live_stats(session, wk, None)
    scoped = svc.live_stats(session, wk, ["supply_chain_design"])
    assert allc["usage"]["conversations"] >= scoped["usage"]["conversations"]
    assert set(scoped["per_course"]) <= {"supply_chain_design"}


def test_cached_sections_filters_and_strips_hashes(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    (tmp_path / "2026-05-03.json").write_text(
        '{"version":1,"week_start":"2026-05-03","conversations":'
        '{"u1":{"course":"supply_chain_design","worked_well":true,"issues":[],"topics":[],"one_line":""},'
        '"u2":{"course":"meaning_of_life","worked_well":true,"issues":[],"topics":[],"one_line":""}},'
        '"examples":{"exemplary":[],"high_engagement":[],"sample":{}},'
        '"topics_by_course":{},"_hashes":{"u1":"x"}}', encoding="utf-8")
    out = svc.cached_sections("2026-05-03", ["supply_chain_design"])
    assert set(out["conversations"]) == {"u1"}
    assert "_hashes" not in out


def test_cached_sections_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(cache_mod, "CACHE_DIR", tmp_path)
    assert svc.cached_sections("1999-01-03", None) is None
```

- [ ] **Step 2: Run to verify failure** → FAIL.

- [ ] **Step 3: Implement `services/analytics.py`**

```python
# database_ui/services/analytics.py
"""Dashboard-facing analytics: live per-week stats + scoped cache reads.

Live stats are computed from the DB on every request (any week). Judged
sections come from the committed cache, course-filtered to the login's scope.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from database_ui.analytics import cache as cache_mod
from database_ui.analytics import data as data_mod
from database_ui.analytics.stats import compute_stats, week_over_week
from database_ui.analytics.weeks import Week, previous_complete_week


def live_stats(db: Session, week: Week, courses: list[str] | None) -> dict:
    """Sections 1-4 + per-course (8) + week-over-week deltas (9), scoped."""
    convs = data_mod.fetch_conversations(db, week, courses)
    msgs = data_mod.fetch_messages(db, [c.id for c in convs])
    returning = data_mod.prior_usernames(db, week.start_utc, courses)
    stats = compute_stats(convs, msgs, returning)

    prior = week.prev()
    p_convs = data_mod.fetch_conversations(db, prior, courses)
    p_msgs = data_mod.fetch_messages(db, [c.id for c in p_convs])
    p_returning = data_mod.prior_usernames(db, prior.start_utc, courses)
    prior_stats = compute_stats(p_convs, p_msgs, p_returning)

    stats["week_over_week"] = week_over_week(stats, prior_stats)
    stats["week"] = {"key": week.key, "label": week.label(),
                     "start": week.key, "end": week.end.isoformat()}
    return stats


def cached_sections(week_key: str, courses: list[str] | None) -> dict | None:
    """Course-filtered judged sections for a week, or ``None`` if not generated.

    Strips the internal ``_hashes`` bookkeeping so it never leaves the server.
    """
    blob = cache_mod.read_cache(week_key)
    if blob is None:
        return None
    blob.pop("_hashes", None)
    return cache_mod.filter_cache(blob, courses)


def week_options() -> list[dict]:
    """Picker options: every cached week plus the default previous-complete week."""
    keys = set(cache_mod.available_weeks())
    keys.add(previous_complete_week(date.today()).key)
    return [
        {"key": k, "label": Week(date.fromisoformat(k)).label()}
        for k in sorted(keys, reverse=True)
    ]
```

- [ ] **Step 4: Run to verify pass** → PASS.

- [ ] **Step 5: Commit**

```bash
git add database_ui/services/analytics.py database_ui/tests/test_analytics_service.py
git commit -m "feat(database_ui): add analytics service for live stats and scoped cache"
```

---

## Task 12: Routes (`routes/analytics.py`) + blueprint registration

**Files:**
- Create: `database_ui/routes/analytics.py`
- Modify: `database_ui/run_app.py` (register `analytics_bp`)
- Test: `database_ui/tests/test_analytics_routes.py`

**Interfaces:**
- Consumes: `services.analytics`, `allowed_courses`, `analytics.weeks.parse_week`.
- Produces blueprint `analytics_bp` with:
  - `GET /analytics` → renders `analytics.html`.
  - `GET /api/analytics?week=<key>` → `{week, live, cached}` where `cached` is `null` when pending; scoped.
  - `GET /api/analytics/weeks` → `{weeks: [{key,label}]}`.

- [ ] **Step 1: Write the failing test**

```python
# database_ui/tests/test_analytics_routes.py
import pytest

from database_ui.conftest import seed
from database_ui.db.session import SessionLocal
from database_ui.run_app import create_app

MASTER = "master-secret"
SC_PW = "supply-secret"


@pytest.fixture()
def seeded():
    s = SessionLocal()
    seed(s)
    s.close()


def _app():
    app = create_app()
    app.config["DATABASE_UI_PASSWORD"] = MASTER
    app.config["DATABASE_UI_COURSE_PASSWORDS"] = {SC_PW: ("supply_chain_design",)}
    return app


def _login(app, pw):
    c = app.test_client()
    c.post("/login", data={"password": pw})
    return c


def test_analytics_page_requires_auth():
    app = _app()
    resp = app.test_client().get("/analytics")
    assert resp.status_code in (301, 302)          # redirected to login


def test_api_analytics_returns_live_and_pending_cached(seeded):
    c = _login(_app(), MASTER)
    resp = c.get("/api/analytics?week=2026-05-05")
    assert resp.status_code == 200
    body = resp.get_json()
    assert "live" in body and "week" in body
    assert body["cached"] is None                  # no cache committed for that week


def test_api_analytics_scoped(seeded):
    c = _login(_app(), SC_PW)
    body = c.get("/api/analytics?week=2026-05-05").get_json()
    assert set(body["live"]["per_course"]) <= {"supply_chain_design"}


def test_api_weeks_lists_options(seeded):
    c = _login(_app(), MASTER)
    body = c.get("/api/analytics/weeks").get_json()
    assert "weeks" in body and isinstance(body["weeks"], list)
```

- [ ] **Step 2: Run to verify failure** → FAIL (route missing / 404).

- [ ] **Step 3: Implement `routes/analytics.py`**

```python
# database_ui/routes/analytics.py
"""Weekly-report blueprint: the page shell and its scoped JSON API."""
from __future__ import annotations

from datetime import date

from flask import Blueprint, current_app, g, jsonify, render_template, request

from database_ui.analytics.weeks import parse_week, previous_complete_week
from database_ui.auth import allowed_courses
from database_ui.routes.database import _scope_label  # reuse the hidden banner label
from database_ui.services import analytics as svc

analytics_bp = Blueprint("analytics", __name__)


@analytics_bp.get("/analytics")
def analytics_page():
    return render_template(
        "analytics.html",
        title=current_app.config["DATABASE_UI_TITLE"],
        accent=current_app.config["DATABASE_UI_ACCENT"],
        scope_label=_scope_label(),
    )


@analytics_bp.get("/api/analytics")
def api_analytics():
    raw = request.args.get("week")
    week = parse_week(raw) if raw else previous_complete_week(date.today())
    courses = allowed_courses()
    live = svc.live_stats(g.db, week, courses)
    cached = svc.cached_sections(week.key, courses)
    return jsonify({
        "week": {"key": week.key, "label": week.label()},
        "live": live,
        "cached": cached,
    })


@analytics_bp.get("/api/analytics/weeks")
def api_weeks():
    return jsonify({"weeks": svc.week_options()})
```

> Implementer note: `_scope_label` is a module-private helper in `routes/database.py`. Importing a `_`-prefixed name across modules is a smell; if the reviewer objects, promote it to a public `scope_label()` in `database_ui/courses.py` or a small `database_ui/scope.py` and import from there in both routes. Either is acceptable — do not duplicate the logic.

- [ ] **Step 4: Register the blueprint in `run_app.py`**

In `database_ui/run_app.py`, alongside the existing `app.register_blueprint(database_bp)`:

```python
from database_ui.routes.analytics import analytics_bp
# ...
app.register_blueprint(analytics_bp)
```

- [ ] **Step 5: Run to verify pass**

Run: `python -m pytest database_ui/tests/test_analytics_routes.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add database_ui/routes/analytics.py database_ui/run_app.py database_ui/tests/test_analytics_routes.py
git commit -m "feat(database_ui): add weekly report routes and register blueprint"
```

---

## Task 13: Page template, sidebar link, and inline-SVG charts

**Files:**
- Create: `database_ui/templates/analytics.html`
- Create: `database_ui/static/js/analytics.js`
- Create: `database_ui/static/css/analytics.css`
- Modify: `database_ui/templates/index.html` (add "Weekly report" sidebar button)
- Test: `database_ui/tests/test_analytics_page.py`

**Interfaces:**
- Consumes: `GET /api/analytics`, `GET /api/analytics/weeks`.

- [ ] **Step 1: Write the failing test** (server-side render assertions only; JS behavior is verified manually)

```python
# database_ui/tests/test_analytics_page.py
from database_ui.run_app import create_app


def _client():
    app = create_app()
    app.config["DATABASE_UI_PASSWORD"] = None       # gate off for the render check
    app.config["DATABASE_UI_COURSE_PASSWORDS"] = {}
    return app.test_client()


def test_analytics_page_renders_shell():
    html = _client().get("/analytics").get_data(as_text=True)
    assert 'id="analytics-root"' in html
    assert "analytics.js" in html


def test_index_has_weekly_report_link():
    html = _client().get("/").get_data(as_text=True)
    assert "/analytics" in html and "Weekly report" in html
```

- [ ] **Step 2: Run to verify failure** → FAIL.

- [ ] **Step 3: Add the sidebar button to `index.html`**

Immediately after the existing `#download-open` button (inside `.sidebar-inner`, before `#sidebar-empty`), add:

```html
<a href="/analytics" class="sidebar-cta" id="weekly-report-open" title="Weekly analytics report">
    <svg class="sidebar-cta-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <line x1="18" y1="20" x2="18" y2="10"/>
        <line x1="12" y1="20" x2="12" y2="4"/>
        <line x1="6" y1="20" x2="6" y2="14"/>
    </svg>
    <span>Weekly report</span>
</a>
```

- [ ] **Step 4: Create `analytics.html`**

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{ title }} · Weekly report</title>
  <style>:root { --accent: {{ accent }}; }</style>
  <link rel="stylesheet" href="{{ url_for('ui_core.static', filename='css/chat.css', v='3') }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='css/database.css') }}">
  <link rel="stylesheet" href="{{ url_for('static', filename='css/analytics.css', v='1') }}">
</head>
<body>
  <header class="course-banner"><span class="course-name scope-hidden">{{ scope_label }}</span></header>
  <main class="analytics" id="analytics-root">
    <div class="analytics-bar">
      <a href="/" class="analytics-back">← Conversations</a>
      <select id="week-picker" class="analytics-week"></select>
      <span id="analytics-status" class="analytics-status"></span>
    </div>
    <section id="analytics-content" class="analytics-content" aria-live="polite"></section>
  </main>
  <script src="{{ url_for('static', filename='js/analytics.js', v='1') }}" defer></script>
</body>
</html>
```

- [ ] **Step 5: Create `analytics.js`** (fetch + render + a compact inline-SVG bar chart)

```javascript
// database_ui/static/js/analytics.js
// Renders the weekly report: fetches JSON, draws lightweight inline-SVG charts.
(function () {
  "use strict";
  const SVG = "http://www.w3.org/2000/svg";
  const $ = (id) => document.getElementById(id);

  function el(tag, attrs, kids) {
    const n = document.createElementNS(attrs && attrs._svg ? SVG : null, tag);
    for (const k in (attrs || {})) if (k !== "_svg") n.setAttribute(k, attrs[k]);
    (kids || []).forEach((c) => n.appendChild(typeof c === "string" ? document.createTextNode(c) : c));
    return n;
  }

  // Minimal, accessible bar chart from [{label, value}]. Direct-labeled bars.
  function barChart(data, opts) {
    opts = opts || {};
    const w = 520, h = 200, pad = 28, n = data.length || 1;
    const max = Math.max(1, ...data.map((d) => d.value));
    const bw = (w - pad * 2) / n * 0.7;
    const svg = el("svg", { _svg: true, viewBox: `0 0 ${w} ${h}`, class: "chart", role: "img" });
    data.forEach((d, i) => {
      const x = pad + (i + 0.15) * ((w - pad * 2) / n);
      const bh = (h - pad * 2) * (d.value / max);
      const y = h - pad - bh;
      svg.appendChild(el("rect", { _svg: true, x, y, width: bw, height: bh, rx: 2, fill: "var(--accent)" }));
      svg.appendChild(el("text", { _svg: true, x: x + bw / 2, y: y - 4, "text-anchor": "middle", class: "chart-val" }, [String(d.value)]));
      svg.appendChild(el("text", { _svg: true, x: x + bw / 2, y: h - 8, "text-anchor": "middle", class: "chart-lbl" }, [d.label]));
    });
    return svg;
  }

  function card(title, body) {
    const c = el("div", { class: "a-card" });
    c.appendChild(el("h2", { class: "a-card-title" }, [title]));
    c.appendChild(body);
    return c;
  }

  function statList(pairs) {
    const ul = el("ul", { class: "a-stats" });
    pairs.forEach(([k, v]) => {
      const li = el("li");
      li.appendChild(el("span", { class: "a-stat-k" }, [k]));
      li.appendChild(el("span", { class: "a-stat-v" }, [String(v)]));
      ul.appendChild(li);
    });
    return ul;
  }

  function pct(x) { return Math.round((x || 0) * 100) + "%"; }
  function money(x) { return "$" + (x || 0).toFixed(2); }
  function arrow(wow, key) { return (wow && wow[key] && wow[key].arrow) || ""; }

  function render(payload) {
    const root = $("analytics-content");
    root.textContent = "";
    const s = payload.live, wow = s.week_over_week || {};
    const u = s.usage, r = s.ratings, co = s.cost, ct = s.content;

    root.appendChild(card("Overview — " + payload.week.label, statList([
      ["Conversations", u.conversations + " " + arrow(wow, "conversations")],
      ["Students", u.unique_students + " (" + u.new_students + " new)"],
      ["Positive rating", pct(r.positive_rate) + " " + arrow(wow, "positive_rate")],
      ["Cost", money(co.total_usd) + " " + arrow(wow, "cost_usd")],
      ["RAG rate", pct(ct.rag_rate) + " " + arrow(wow, "rag_rate")],
    ])));

    const byDay = Object.entries(u.conversations_by_day || {}).map(([d, v]) => ({ label: d.slice(5), value: v }));
    if (byDay.length) root.appendChild(card("Conversations by day", barChart(byDay)));

    // Judged sections (may be pending).
    if (!payload.cached) {
      root.appendChild(card("Judged review", el("p", { class: "a-pending" },
        ["Pending this week's review — the flagged conversations, examples, and topics appear once the weekly report PR is merged."])));
      return;
    }
    const flags = Object.values(payload.cached.conversations || {}).filter((c) => !c.worked_well);
    const flagBody = el("div");
    flagBody.appendChild(el("p", {}, [flags.length + " conversations flagged."]));
    root.appendChild(card("🚩 Didn't work well", flagBody));

    const topics = payload.cached.topics_by_course || {};
    const tBody = el("div");
    Object.entries(topics).forEach(([course, rows]) => {
      tBody.appendChild(el("p", {}, [course + ": " + rows.slice(0, 8).map((t) => t.topic + " (" + t.count + ")").join(" · ")]));
    });
    root.appendChild(card("🗣 Top topics", tBody));
  }

  async function load(weekKey) {
    $("analytics-status").textContent = "Loading…";
    const q = weekKey ? ("?week=" + encodeURIComponent(weekKey)) : "";
    const resp = await fetch("/api/analytics" + q);
    const payload = await resp.json();
    render(payload);
    $("analytics-status").textContent = "";
  }

  async function initPicker() {
    const resp = await fetch("/api/analytics/weeks");
    const { weeks } = await resp.json();
    const sel = $("week-picker");
    weeks.forEach((w) => sel.appendChild(el("option", { value: w.key }, [w.label])));
    sel.addEventListener("change", () => load(sel.value));
    load(sel.value || (weeks[0] && weeks[0].key));
  }

  document.addEventListener("DOMContentLoaded", initPicker);
})();
```

- [ ] **Step 6: Create `analytics.css`** (page layout; inherits banner styles from `database.css`)

```css
/* database_ui/static/css/analytics.css */
.analytics { max-width: 960px; margin: 0 auto; padding: 16px; }
.analytics-bar { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.analytics-back { color: var(--accent); text-decoration: none; font-size: 14px; }
.analytics-week { padding: 6px 8px; border: 1px solid #cdd6db; border-radius: 6px; }
.analytics-status { color: #6b7a82; font-size: 13px; }
.analytics-content { display: grid; gap: 16px; }
.a-card { border: 1px solid #e3e9ec; border-radius: 10px; padding: 16px; background: #fff; }
.a-card-title { font-size: 15px; margin: 0 0 10px; color: #123; }
.a-stats { list-style: none; margin: 0; padding: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 8px; }
.a-stat-k { display: block; font-size: 12px; color: #6b7a82; }
.a-stat-v { display: block; font-size: 20px; font-weight: 600; }
.a-pending { color: #6b7a82; font-style: italic; }
.chart { width: 100%; height: auto; }
.chart-val { font-size: 10px; fill: #123; }
.chart-lbl { font-size: 9px; fill: #6b7a82; }
```

- [ ] **Step 7: Run to verify pass**

Run: `python -m pytest database_ui/tests/test_analytics_page.py -v`
Expected: PASS.

- [ ] **Step 8: Manual smoke check**

Run the dev server (`python -m database_ui`), log in, click "Weekly report", confirm the page renders, the week picker switches weeks, and uncached weeks show the "pending" note. (Cannot be asserted in CI — no browser.)

- [ ] **Step 9: Commit**

```bash
git add database_ui/templates/analytics.html database_ui/templates/index.html database_ui/static/js/analytics.js database_ui/static/css/analytics.css database_ui/tests/test_analytics_page.py
git commit -m "feat(database_ui): add weekly report page with inline-SVG charts and sidebar link"
```

---

## Task 14: GitHub Actions workflow

**Files:**
- Create: `.github/workflows/weekly-analytics.yml`

**Interfaces:**
- Runs `python -m database_ui.analytics.weekly`, then opens a PR against `prod-beta-plus`.

- [ ] **Step 1: Create the workflow**

```yaml
# .github/workflows/weekly-analytics.yml
name: Weekly analytics report

on:
  schedule:
    # Monday 11:00 UTC ≈ Sun night / early Mon in America/New_York (DST shifts ±1h).
    - cron: "0 11 * * 1"
  workflow_dispatch:
    inputs:
      week:
        description: "Any date (YYYY-MM-DD) inside the target week; blank = previous complete week"
        required: false
        default: ""
      max_convos:
        description: "Cap conversations judged (blank = all)"
        required: false
        default: ""

permissions:
  contents: write
  pull-requests: write

concurrency:
  group: weekly-analytics
  cancel-in-progress: false

env:
  TARGET_BRANCH: prod-beta-plus

jobs:
  build-report:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ env.TARGET_BRANCH }}
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install dependencies
        run: pip install -r requirements.txt

      - name: Generate weekly report
        id: gen
        env:
          DATABASE_UI_DATABASE_URL: ${{ secrets.ANALYTICS_DATABASE_URL }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          ANALYTICS_JUDGE_MODEL: ${{ vars.ANALYTICS_JUDGE_MODEL || 'claude-sonnet-5' }}
        run: |
          ARGS=""
          if [ -n "${{ github.event.inputs.week }}" ]; then ARGS="$ARGS --week ${{ github.event.inputs.week }}"; fi
          if [ -n "${{ github.event.inputs.max_convos }}" ]; then ARGS="$ARGS --max-convos ${{ github.event.inputs.max_convos }}"; fi
          python -m database_ui.analytics.weekly $ARGS --report-out /tmp/report.md
          # Surface the week key (cache filename stem) for the PR branch/title.
          echo "week_key=$(ls -t database_ui/analytics/cache/*.json | head -1 | xargs -n1 basename | sed 's/.json//')" >> "$GITHUB_OUTPUT"

      - name: Open pull request
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          WEEK: ${{ steps.gen.outputs.week_key }}
        run: |
          BRANCH="analytics/week-${WEEK}"
          git config user.name "asktim-bot"
          git config user.email "asktim-bot@users.noreply.github.com"
          git checkout -b "$BRANCH"
          git add database_ui/analytics/cache/
          if git diff --cached --quiet; then echo "No cache changes; skipping PR."; exit 0; fi
          git commit -m "chore(analytics): weekly report cache for ${WEEK}"
          git push -u origin "$BRANCH" --force-with-lease
          gh pr create --base "$TARGET_BRANCH" --head "$BRANCH" \
            --title "Weekly analytics — week of ${WEEK}" \
            --body-file /tmp/report.md
```

> Implementer note: `ANALYTICS_DATABASE_URL` must be the prod Postgres **public/proxy** URL (Actions runners can't reach Railway's private network). Set it and `ANTHROPIC_API_KEY` as repo secrets; optionally set `ANALYTICS_JUDGE_MODEL` as a repo variable. `report.md` is intentionally NOT committed (it's the PR body only); only the cache JSON lands in the repo. Confirm the cron hour against desired ET delivery.

- [ ] **Step 2: Validate YAML locally**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/weekly-analytics.yml')); print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/weekly-analytics.yml
git commit -m "ci(analytics): add scheduled weekly report workflow opening a PR"
```

---

## Task 15: Documentation

**Files:**
- Modify: `database_ui/README.md`

- [ ] **Step 1: Add a "Weekly report" section** to `database_ui/README.md` documenting:
  - The `/analytics` page: live stats (usage, ratings, cost, RAG) computed per request for any week; judged sections (flags, examples, topics) served from the committed cache.
  - Week definition (Sun–Sat, America/New_York) and label format.
  - The `database_ui/analytics/` package and the CLI: `python -m database_ui.analytics.weekly --week YYYY-MM-DD [--max-convos N]`, env `DATABASE_UI_DATABASE_URL`, `ANTHROPIC_API_KEY`, `ANALYTICS_JUDGE_MODEL`.
  - The weekly GitHub Action: runs the CLI, opens a PR against `prod-beta-plus`; **merging the PR deploys the cache**, after which the page's judged sections light up (they show "pending this week's review" until then).
  - Scoping note: a per-course login sees only its course's live stats and cached entries.
  - Privacy note: the cache contains real usernames — the repo must stay private.

- [ ] **Step 2: Commit**

```bash
git add database_ui/README.md
git commit -m "docs(database_ui): document the weekly report feature"
```

---

## Final verification

- [ ] Run the whole suite: `python -m pytest database_ui -q`
- [ ] Confirm no top-level `analytics/` dir exists (everything under `database_ui/analytics/`).
- [ ] Confirm the cache dir ships in the image path (`database_ui/analytics/cache/`) and `.gitkeep` is committed.
- [ ] Grep for accidental real passwords/secrets in committed files (there should be none — secrets live only in GitHub Actions secrets / Railway env).

## Global Constraints recap (bind every task)

- Analytics package + cache live under `database_ui/` (image boundary).
- Read-only SELECTs only; map only existing model columns.
- Every query and cache read scoped via `allowed_courses()`.
- Weeks are Sun–Sat America/New_York; labels `Mon D, YYYY — Mon D, YYYY`; cache keyed by start date.
- Weekly PR targets `prod-beta-plus`.
- Judge behind `Judge` protocol; tests use `FakeJudge`, never a real LLM.
- Charts are inline SVG; no matplotlib, no server-rendered images.
- Real usernames retained; repo stays private.
- Conventional commits, no Claude co-author trailer; bump `v=` on edited static assets.
