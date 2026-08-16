# AskTIM Weekly Report — design

**Date:** 2026-08-12
**Apps:** `database_ui` (read-only review dashboard) + a new `analytics/` package + one GitHub Actions workflow

## Goal

Turn the 2026-08-11 meeting's "Analytics & evaluation" action item into a
**"Weekly report" view inside `database_ui`**: a scoped Analytics page that shows
each week's usage, engagement, ratings, cost, and content/RAG statistics (live),
plus an LLM-judged list of conversations where the tutor **didn't work well**,
surfaced **example** conversations, and the **topics students asked about most**
(precomputed weekly). This gives the team an automated weekly pulse and concrete
leads for manual ground-truthing and user interviews.

Explicitly **out** of this design: Laura's weekly feedback form (dropped from
scope for now).

## Current state

- `database_ui` is a read-only Flask dashboard over the production conversation
  DB. It already maps the shared schema read-only (`db/models.py`:
  `Conversation`, `Message`, `UploadedImage`, `UploadedFile`) and enforces
  **per-course access scoping** (`auth.py` `allowed_courses() -> list[str] | None`;
  `None` = master/all-access, a list = restrict). Routes live in
  `routes/database.py`, read queries in `services/conversations.py`.
- `Message` carries the analytics substrate already: `rating` (-1/0/1 thumb),
  `cost_usd`, `usage_json` (model id + token counts), `retrieved_context` (RAG
  chunks JSON), `pedagogical_reasoning`, `role`, `turn`, `created_at`.
  `Conversation` carries `course`, `exercise_number`, `exercise_kind`,
  `focus_problem`, `tutor_prompt`, `username`, `started_at`, `last_active_at`.
- A `visualization/` package already renders matplotlib charts in a house style
  (colorblind-safe palette, "bare + titled" variants). New charts reuse it.
- The repo is on GitHub (`bonbon-on-fire/asktim_llm_tutor_project`) with **no**
  workflows yet. LLM stack available: `langchain-anthropic` / `langchain-openai`.
- The app is **read-only by construction** and never migrates. This design
  preserves that: the dashboard adds only `SELECT`s and reads a committed cache
  file; it never writes the DB.

## Decisions (locked)

- **Delivery:** a "Weekly report" button in the `database_ui` sidebar (next to
  "Download data") opens an Analytics page. No new web service.
- **Two data paths.** Cheap statistics are **live SQL**, computed per request for
  any selected week. The expensive LLM work (failure judging, example selection,
  topic tagging) is **precomputed once a week** and read from a committed JSON
  cache — judging hundreds of conversations per click would be too slow/costly.
- **Judge model:** a mid-tier model (Claude Sonnet) judges **every** conversation
  in the week. Verdicts are cached by conversation id + content hash so re-runs
  and backfills are idempotent and cheap (~$1–3/week at current volume).
- **Failure signal:** union of thumbs-down (`rating == -1`) **and** the LLM
  judge. Judge rubric flags four issue types: gave-away-answer, factual/content
  error, unhelpful/dead-end, RAG/grounding problem — each with a severity and a
  short supporting quote.
- **Scope:** both an **all-courses overview** and a **per-course breakdown**.
  Everything respects the login's `allowed_courses()` scope — a scoped reviewer's
  Weekly report only covers their course(s).
- **Week definition:** **Sunday → Saturday**, in **America/New_York** (so a "day"
  matches when students actually worked; DB timestamps are tz-aware). Default
  selection is the previous complete week; a picker browses history.
- **Week labels (user-facing):** date ranges like `Aug 9, 2026 — Aug 15, 2026`
  (abbreviated month, no leading-zero day). Cache filenames key off the week's
  **start date** (`analytics/cache/2026-08-09.json`) — unambiguous for Sun–Sat
  weeks (ISO `W##` assumes Monday starts).
- **Cache storage:** committed JSON in the repo (one file per week). No new DB
  writes, no new infra; versioned alongside the code.
- **Cache production & delivery:** a scheduled **GitHub Actions** workflow runs
  the judge + topic tagging Sunday night / early Monday for the just-ended week,
  and **opens a Pull Request** adding that week's cache JSON (plus a short
  human-readable `report.md`). The PR is the team's ground-truthing/review
  surface; **merging it** lands the cache so the in-app view can render that
  week's judged sections after `database_ui` redeploys.
- **Privacy:** the report shows **real usernames/emails** (needed to follow up
  for interviews). Accepted tradeoff: identities live in git history and in the
  cache, so **the GitHub repo must remain private** and the cache is subject to
  the same handling as the rest of the repo.

## The Analytics page — what it shows

A selected week (default: previous complete Sun–Sat), a **date-range week
picker** to browse back, all scoped to the login's course(s). Sections:

1. **Usage & engagement** — conversations; unique students; total messages (split
   student vs tutor); messages-per-conversation distribution; conversation
   duration (`started_at`→`last_active_at`); new vs returning students; active
   days; conversations-by-day; abandoned/very-short count.
2. **Ratings & satisfaction** — 👍/👎 counts and positive rate; % of tutor turns
   rated; % of conversations with any rating; broken out by course and exercise.
3. **Cost** — total weekly spend; cost per conversation / student / course /
   model / exercise; token totals (from `usage_json`); most expensive
   conversations; model mix.
4. **Content & RAG** — top exercises/practices by volume (per course); exercise
   vs practice split; `focus_problem` usage; RAG hit rate (share of tutor turns
   with `retrieved_context`); avg chunks per RAG turn; RAG rate by course; tutor
   prompt version (`tutor_prompt`) distribution.
5. **🚩 Where the tutor didn't work well** *(cached)* — ranked flagged
   conversations, each: course · exercise · student · issue type · severity ·
   supporting quote · one-line judge reason · click-through into the existing
   transcript view. Plus counts by issue type and the 👎∩judge overlap.
6. **Example conversations** *(cached)* — ⭐ exemplary (worked well) · 🔥
   high-engagement (longest/deepest) · 🎲 representative random sample, a few per
   course, each linking into the transcript viewer.
7. **🗣 Common topics students asked about** *(cached)* — ranked topics per course
   (LLM-tagged during the judge pass, 1–3 topics per conversation, aggregated)
   with counts and example student questions.
8. **Per-course breakdown** — an all-courses overview first, then a collapsible
   section per course repeating §1–7 for that course.
9. **Week-over-week deltas** — ▲▼ indicators on headline metrics (conversations,
   students, cost, positive-rating rate, RAG rate) vs the prior week.
10. **Run/meta** — the week; how many conversations were judged; the judge model;
    when the cache was generated. If no cache exists yet for the selected week,
    §5–7 show a "pending this week's review" state and §1–4, 8–9 still render live.

### Wireframe

```
┌─ AskTIM · Database Beta+ ──────────────────────────────────────┐
│ [ Download data ]   [ 📊 Weekly report ]   ‹ Aug 9–15, 2026 ›   │
├────────────────────────────────────────────────────────────────┤
│ OVERVIEW — all courses            ▲▼ vs prior week             │
│  342 convos ▲ · 88 students ▲ · 👍85% ▲ · $6.40 · RAG 44%     │
│  [usage-by-day]  [ratings-by-course]  [cost-by-course/model]   │
│                                                                │
│ 🚩 DIDN'T WORK WELL (48: 37👎 + 23 judge)                       │
│  1. SC2x P7 · a12f · guiscarello · GAVE-AWAY · high  →open      │
│     "…so the EOQ is 1,200 units, just plug it in."             │
│                                                                │
│ ⭐ Worked well   🔥 High engagement   🎲 Sample   (links)       │
│ 🗣 TOP TOPICS (SC2x): EOQ (41) · safety stock (28) · …         │
│                                                                │
│ ▸ MIT CTL.SC2x Supply Chain Design   210 convos · $3.10 · 88%👍│
│ ▸ MIT 21A.157 The Meaning of Life    …                        │
└────────────────────────────────────────────────────────────────┘
```

## The `analytics/` package (cache producer + shared compute)

A new package, sibling to `visualization/` and `database_ui/`:

- **`data.py`** — read-only queries over `database_ui.db.models`, windowed to a
  Sun–Sat week in America/New_York. Reused by both the live dashboard stats and
  the weekly job so the two never diverge.
- **`stats.py`** — descriptive statistics (§1–4) + per-course slices + prior-week
  deltas. Pure functions over query results; no I/O; unit-tested.
- **`judge.py`** — `judge_conversation(convo) -> Verdict` using Claude Sonnet.
  `Verdict` = `{worked_well: bool, issues: [{type, severity, quote}], topics:
  [str], one_line: str}`. Cached by conversation id + content hash. The judge is
  behind an interface so tests inject a deterministic `FakeJudge` (no API calls).
- **`topics.py`** — aggregate the per-conversation `topics` into ranked
  per-course topic lists with example questions.
- **`flags.py`** — combine `rating == -1` and judge verdicts into the ranked
  failure list (§5), with issue-type counts and overlap.
- **`examples.py`** — pick the ⭐/🔥/🎲 sets (§6). Random sampling is seeded from
  the week key for reproducibility.
- **`charts.py`** — matplotlib charts reusing `visualization/`'s palette and
  bare/titled pattern. The **dataviz** skill is consulted when these are built.
- **`report.py`** — render the human-readable `report.md` for the PR body.
- **`weekly.py`** — CLI entrypoint: `python -m analytics.weekly --week
  2026-08-09` (defaults to the previous complete week). Reads the DB, runs judge +
  topics, writes `analytics/cache/<start-date>.json`, renders `report.md`.
- **`tests/`** — seeded-SQLite fixtures (same pattern as `database_ui/tests`) +
  `FakeJudge`; cover the stats math, flag/example/topic aggregation, cache
  read/write round-trip, and a chart smoke test. No test calls an LLM.

### Cache JSON shape (`analytics/cache/2026-08-09.json`)

```json
{
  "week_start": "2026-08-09", "week_end": "2026-08-15", "tz": "America/New_York",
  "generated_at": "2026-08-17T05:12:00-04:00",
  "judge_model": "claude-sonnet-...", "judged_count": 342,
  "conversations": {
    "<uuid>": {
      "course": "supply_chain_design", "worked_well": false,
      "issues": [{"type": "gave_away_answer", "severity": "high",
                  "quote": "…so the EOQ is 1,200 units…"}],
      "topics": ["EOQ", "order quantity"], "one_line": "handed a final answer"
    }
  },
  "examples": {"exemplary": ["<uuid>"], "high_engagement": ["<uuid>"],
               "sample": {"supply_chain_design": ["<uuid>"]}},
  "topics_by_course": {"supply_chain_design":
     [{"topic": "EOQ", "count": 41, "examples": ["how do I find EOQ?"]}]}
}
```

The dashboard reads this file from its deployed image. Live stats (§1–4, 8–9) are
always computed from the DB regardless of cache presence.

## `database_ui` changes

- **`routes/analytics.py`** — new blueprint. `GET /analytics` renders the page
  shell; `GET /api/analytics?week=<start-date>` returns the week's live stats +
  the cached blob (if present), filtered to `allowed_courses()`. A scoped login
  never receives another course's rows or cached entries. `GET
  /api/analytics/weeks` lists available weeks for the picker.
- **`services/analytics.py`** — live SQL stats (delegating to `analytics.stats`
  over `analytics.data`) + a cache reader that loads and **course-filters** the
  committed JSON by `allowed_courses()`.
- **`templates/analytics.html`** + static JS/CSS — the page and week picker,
  matching the existing review shell's styling; charts follow the dataviz system.
- **Sidebar** — a "Weekly report" button next to "Download data" in
  `templates/index.html`.
- Scope enforcement mirrors the existing pattern: `allowed_courses()` gates both
  the live queries and the cache filtering; nothing widens access.

## GitHub Actions workflow (`.github/workflows/weekly-analytics.yml`)

- `on: schedule` (Sunday night / early Monday, America/New_York) **and**
  `workflow_dispatch` with a `week` input (manual runs and backfill).
- Secrets: `ANALYTICS_DATABASE_URL` (prod Postgres **public** proxy URL) and
  `ANTHROPIC_API_KEY`.
- Permissions: `contents: write`, `pull-requests: write` (opens the PR with the
  built-in `GITHUB_TOKEN`).
- Steps: checkout → setup-python → `pip install -r requirements.txt` → `python -m
  analytics.weekly --week <prev week>` → create a branch + open a PR titled for
  the week's date range, body = the rendered `report.md`.
- **Deploy dependency (confirm at plan time):** the cache must land on whatever
  branch `database_ui` deploys from, so merging the weekly PR (or a follow-up
  fast-forward) reaches the deployed dashboard.

## Cost & safety

- Judging is cached by conversation content hash → re-runs/backfills don't re-pay.
- `--max-convos` safety flag exists (default judges all); skipped items are
  recorded in the cache/report so coverage is never silently capped.
- `--week` is idempotent: regenerate any past week to fix or backfill.

## Testing

- **`analytics/tests`** — stats math on seeded fixtures; flag/example/topic
  aggregation; cache round-trip; `FakeJudge` determinism; chart smoke test.
- **`database_ui/tests`** — `/analytics` and `/api/analytics` behind the auth
  gate; a **scoped** login sees only its course's live stats **and** only its
  course's cached entries; a **master** login sees all; a week with no cache
  renders live stats with §5–7 in the "pending" state; the week picker lists
  available weeks.

## Out of scope

- Laura's weekly feedback form and any feedback storage (dropped for now).
- Any DB schema change or migration (dashboard stays read-only).
- Real-time / on-click LLM judging (precomputed weekly instead).
- Per-user accounts, alerting, or auto-merging the weekly PR (manual review).
```
