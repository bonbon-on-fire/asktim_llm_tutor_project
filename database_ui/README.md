# database_ui

**🔗 Live: <https://asktim-database.up.railway.app/>** (password-gated)

A **read-only** dashboard for reviewing real AskTIM conversation data. It looks
like the `main_ui` chat UI (same MIT-crimson styling) but strips every input
affordance — there is no composer, no "new chat", no writes of any kind. It
lists **all** conversations in the database (across every student) and renders a
selected one's full transcript. Each tutor turn shows the same review metadata
the Sandbox surfaces: the model + estimated cost (e.g. `gpt-5.4 ($0.0338)`), the
pedagogical reasoning, a collapsible "RAG retrieval" list of the chunks pulled
that turn, and **display-only** thumbs reflecting the student's stored rating
(read-only tool — the rating is shown highlighted, never editable). Any uploaded
images are rendered inline. The sidebar opens by default on wider screens
(>480px) and stays closed on narrow/mobile screens (where it covers the full
transcript) until the toggle is tapped. Each sidebar entry leads with the
student's username in the crimson accent (anonymous rows read "Anonymous",
italicized), then the full course name, then the exercise header with the
conversation's running total cost appended. Any non-image attachments a student
uploaded (PDF/CSV/XLSX/DOCX/TXT) render as "📎 filename" chips under
the message — the same treatment `main_ui`/`sandbox_ui` give them; clicking a
chip downloads the stored file (served from `/api/file/<id>` as an attachment).
Uploaded images can be clicked to view large in a lightbox, matching the live apps.

A **Download data** button in the sidebar (the same solid-accent CTA sandbox_ui
uses for "Edit context") opens a wizard: the first page multi-selects courses
(a sandbox-style dropdown, none selected by default), then each selected course
gets its own page with a multi-select dropdown of that course's
exercises/practice — so the page count is `1 + (courses chosen)`. The final page
downloads the
matching conversations as a single CSV (one row per message: content,
pedagogical reasoning, rating, model, cost, raw `usage_json` /
`retrieved_context`, and per-message image + file counts). Read-only like the
rest of the app — the export is pure `SELECT`.

Built to review **`main_ui`**'s production database. See the full design +
checklist in [`PLANNING.md`](PLANNING.md).

## Read-only by construction

- `db/models.py` maps only the columns shared by `main_ui` and `sandbox_ui`
  (all-nullable, `viewonly=True` relationships), so the same code reads either
  DB unchanged and never crashes on sandbox-only columns. It currently maps
  `conversations`, `messages`, `uploaded_images`, and `uploaded_files`
  (non-image attachments: CSV/XLSX/PDF/DOCX/TXT — the chips surface filename/kind
  only and the extracted text is never served, though the raw bytes are
  downloadable via `/api/file/<id>`). The shared DB
  also has a `feedback` (conversation-level 1-5 star ratings, now dormant) table
  this viewer doesn't browse yet.
- Beyond `content`/`pedagogical_reasoning`, `db/models.py` maps the tutor-turn
  review columns — all shared by both schemas (`ui_core.db.models_common`), so
  mapping them is safe against either DB: `rating` (int `-1`/`0`/`1`, the
  student's thumb, which replaced the old conversation-level star feedback),
  `cost_usd` + `usage_json` (estimated turn cost and its model-id/token
  breakdown), and `retrieved_context` (the turn's RAG chunks as JSON). The viewer
  surfaces all of these — the thumbs are **display-only** (this app never
  writes).
- The two JSON parsers (`usage_json` → model id, `retrieved_context` → chunk
  records) live in [`ui_core/usage.py`](../ui_core/usage.py) — dependency-light
  and in this app's image — and are shared with `ui_core.services.conversation`,
  so both readers of the `messages` table parse them the same way.
- No `create_all`, no migrations. The per-request session (`run_app.py`) always
  rolls back, never commits.
- Every route is behind a password gate (`auth.py`'s `init_auth`
  before-request guard + `_PUBLIC_ENDPOINTS`); the API endpoints intentionally
  drop the per-viewer ownership checks the live apps use (review sees everyone
  in its scope).
- **Per-course access scoping.** Two kinds of password log in: the **master**
  password (`DATABASE_UI_PASSWORD`) sees every course, and any **course
  password** (`DATABASE_UI_COURSE_PASSWORDS`) is scoped to just the course(s) it
  maps to. Login resolves a `Scope`; `allowed_courses()` returns `None` (no
  filter) for master or the allowed course-key list for a scoped login, and
  every data route (list, transcript, image/file, export filters + rows) filters
  by it — a scoped viewer can't list, open, or export another course's data.
  A login scoped to several courses sees the union of just those courses. The
  scope is **invisible to the reviewer**: the current login's access (the course
  name, or `Master`) is written into the top banner in the banner's own white,
  so it reads as an empty bar and a scoped reviewer can't tell the view is
  filtered — an admin reveals it by selecting/highlighting the header text.
  Passwords are compared
  with `hmac.compare_digest`; malformed `DATABASE_UI_COURSE_PASSWORDS` fails
  closed to "no course access" (the master password still works) — a bad config
  never widens access.

## Architecture: what's shared with `main_ui` / `sandbox_ui`, what isn't

Unlike `main_ui`/`sandbox_ui`, this app keeps its **own** `run_app.py::create_app()`
instead of the shared `ui_core.app_factory` — it's read-only, auth-gated, and has
no chat, so the shared factory's chat/session wiring doesn't apply. It does still
share some of `ui_core`:

- `db/session.py` is a thin wrapper over `ui_core.db.session` (engine + session
  factory, with `pool_pre_ping` and Postgres-URL normalization).
- It registers the shared `ui_core.web.static_blueprint` to serve `chat.css` at
  `/ui-core/css/chat.css` (so the review shell matches `main_ui`'s styling); that
  blueprint's endpoint (`ui_core.static`) is allowlisted in `auth.py`'s
  `_PUBLIC_ENDPOINTS` so the login page can load it before authing. The same
  blueprint also serves the vendored KaTeX assets and `katex-marked.js`; tutor
  messages are rendered via the shared `renderTutorMarkdown` helper, so
  markdown + `\(...\)`/`\[...\]` LaTeX math shows up exactly as students saw it
  in `main_ui`/`sandbox_ui` (`$...$` stays plain text — reserved for currency).

Routes live in `routes/database.py`; the read-only queries backing them live in
`services/conversations.py` — the conversation list (with each conversation's
message count, snippet, and summed `total_cost_usd`, batched to avoid N+1), one
conversation's full transcript (`pedagogical_reasoning`, model + `cost_usd`, RAG
`retrieved`, per-message `rating`), and image/file bytes. Course keys are resolved to
their full display names (e.g. `MIT CTL.SC2x Supply Chain Design`) via a mirror
in `courses.py` — `database_ui`'s image excludes `curriculum/`, so it can't read
`course_name.txt` at runtime the way the live apps do.

## Run locally

```powershell
# Point at a database and set the gate password, then start the dev server.
$env:DATABASE_UI_DATABASE_URL = "<sqlite or postgres url>"   # e.g. the prod public URL
$env:DATABASE_UI_PASSWORD     = "some-shared-password"
$env:DATABASE_UI_SECRET_KEY   = "any-random-string"
python -m database_ui                                      # http://127.0.0.1:5003
```

To review the **production** DB from your machine, set `DATABASE_UI_DATABASE_URL` to
the main Postgres's **public** URL (`DATABASE_PUBLIC_URL` in Railway — the
`...proxy.rlwy.net` host; the internal `*.railway.internal` host only resolves
inside Railway).

## Environment variables

| Variable | Required | Description |
| -------- | -------- | ----------- |
| `DATABASE_UI_DATABASE_URL` | Yes (prod) | DB to read. Falls back to `DATABASE_URL`, then local SQLite. |
| `DATABASE_UI_PASSWORD` | Yes (deploy) | **Master** password — sees every course. Unset ⇒ open (local dev only); the deploy entrypoint refuses to start without it. |
| `DATABASE_UI_COURSE_PASSWORDS` | No | Per-course scoped logins. JSON list of `{"password": str, "courses": [course_key, …]}` entries; each password sees only its listed course(s). Empty/malformed ⇒ no scoped access (master still works). |
| `DATABASE_UI_SECRET_KEY` | Recommended | Flask session signing key (signs the scope into the login cookie). Has an insecure dev default. |
| `DATABASE_UI_TITLE` | No | Browser-tab + login-page title. Default `AskTIM Database`. (The sidebar heading is a fixed `AskTIM · Database Beta+`.) |
| `DATABASE_UI_ACCENT` | No | Accent color. Default `#126f9a` (teal-blue, = sandbox_ui). |
| `DATABASE_UI_COOKIE_MAX_AGE` | No | Login-session cookie lifetime, in seconds. Default 30 days. |
| `PORT` | No | Default `5003`. |

## Deploy (Railway)

Deployed as the **askTIM-database** service (→ <https://asktim-database.up.railway.app/>),
reading the same Postgres as **askTIM-main**. To reproduce:

1. New service in the `tutors (UW, humanities)` project, built from
   [`Dockerfile_database`](../Dockerfile_database) (entrypoint
   [`scripts/railway-entrypoint-database.sh`](../scripts/railway-entrypoint-database.sh)).
2. Set variables:
   - `DATABASE_URL = ${{<main Postgres>.DATABASE_URL}}` (reference askTIM-main's
     Postgres — shares it over the private network; `DATABASE_UI_DATABASE_URL`
     also works and takes precedence).
   - `DATABASE_UI_PASSWORD` (master) and `DATABASE_UI_SECRET_KEY` (secrets).
   - Optional `DATABASE_UI_COURSE_PASSWORDS` (JSON) to hand course staff a
     password scoped to only their own course, e.g.
     `[{"password": "…", "courses": ["supply_chain_design"]}]`.
3. Generate a domain. The entrypoint fails closed if `DATABASE_UI_PASSWORD` is unset,
   so the dashboard is never exposed ungated.

## Endpoints

| Route | Purpose |
| ----- | ------- |
| `GET /` | review shell (sidebar + transcript); redirects to `/login` if not authed |
| `GET/POST /login`, `GET /logout` | password gate (master or per-course scoped) |
| `GET /api/conversations?sort=date\|student&limit=&offset=` | list all conversations |
| `GET /api/conversation/<uuid>` | one conversation's full transcript |
| `GET /api/image/<int>` | serve an uploaded image's bytes |
| `GET /api/file/<int>` | download an uploaded non-image file's bytes |
| `GET /api/export/filters` | list courses + their assignments for the download wizard |
| `GET /api/export.csv?assignment=<course>::<exercise>&…` | download selected conversations as a one-row-per-message CSV |
| `GET /analytics` | weekly report page — see [Weekly report](#weekly-report) |
| `GET /health` | liveness (open, no auth) |

## Weekly report

`GET /analytics` shows a Sunday–Saturday weekly report. Weeks are defined in
America/New_York (`database_ui/analytics/weeks.py`); a week's label is
`Mon D, YYYY — Mon D, YYYY` (em dash), e.g. `Aug 9, 2026 — Aug 15, 2026`. The
page has two kinds of content:

- **Live stats** — usage, ratings, cost, and RAG numbers — are computed
  per request straight from the DB for whichever week is selected, so they're
  always current, including for the in-progress week.
- **Judged sections** — flags, example conversations, and topic
  aggregation — are LLM-judged and served from the committed cache
  (`database_ui/analytics/cache/`), not computed live. Until a week's cache
  exists, that part of the page shows "Pending this week's review — the
  flagged conversations, examples, and topics appear once the weekly report
  PR is merged."

**Scoping.** Like the rest of the app, `/analytics` and `/api/analytics`
respect `allowed_courses()`: a per-course login only sees its own course's
live stats and its own course's entries in the cached sections. The master
password sees everything.

### Generating the cache

The judging + caching logic lives in `database_ui/analytics/` (data
fetching, the LLM judge, flags/examples/topics, the cache writer). Run it
with:

```bash
python -m database_ui.analytics.weekly --week YYYY-MM-DD [--max-convos N]
```

`--week` is any date inside the target week (defaults to the previous
complete week); `--max-convos` caps how many conversations get judged.
Relevant environment variables:

| Variable | Description |
| -------- | ----------- |
| `DATABASE_UI_DATABASE_URL` | DB to read (same variable `database_ui` itself uses). |
| `ANTHROPIC_API_KEY` | Used by the LLM judge. |
| `ANALYTICS_JUDGE_MODEL` | Judge model id. Defaults to `claude-sonnet-5`. |

### Weekly GitHub Action

[`.github/workflows/weekly-analytics.yml`](../.github/workflows/weekly-analytics.yml)
runs the CLI on a schedule (and on manual dispatch), then opens a pull
request against `prod-beta-plus` with the updated cache files. **Merging
that PR is what deploys the cache** — only then do the judged sections on
`/analytics` light up for that week; until it's merged, the page shows the
"pending this week's review" note above.

**Privacy.** The cache contains real student usernames (in flags and
example conversations), so it must never be exposed outside a private repo.
