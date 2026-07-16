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
images are rendered inline. Each sidebar entry leads with the student's username
in the crimson accent (anonymous rows read "Anonymous", italicized), then the
full course name, then the exercise header with the conversation's running total
cost appended.

Built to review **`main_ui`**'s production database. See the full design +
checklist in [`PLANNING.md`](PLANNING.md).

## Read-only by construction

- `db/models.py` maps only the columns shared by `main_ui` and `sandbox_ui`
  (all-nullable, `viewonly=True` relationships), so the same code reads either
  DB unchanged and never crashes on sandbox-only columns. It currently maps
  `conversations`, `messages`, and `uploaded_images` only — the shared DB also
  now has `uploaded_files` (non-image attachments: CSV/XLSX/PDF/DOCX/TXT) and
  `feedback` (conversation-level 1-5 star ratings, now dormant) tables, but this
  viewer doesn't browse them yet.
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
- Every route is behind a shared-password gate (`auth.py`'s `init_auth`
  before-request guard + `_PUBLIC_ENDPOINTS`); the API endpoints intentionally
  drop the per-viewer ownership checks the live apps use (review sees everyone).

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
`retrieved`, per-message `rating`), and image bytes. Course keys are resolved to
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
| `DATABASE_UI_PASSWORD` | Yes (deploy) | Shared password for the login gate. Unset ⇒ open (local dev only); the deploy entrypoint refuses to start without it. |
| `DATABASE_UI_SECRET_KEY` | Recommended | Flask session signing key. Has an insecure dev default. |
| `DATABASE_UI_TITLE` | No | Browser-tab + login-page title. Default `AskTIM Database`. (The sidebar heading is a fixed `AskTIM · Database Beta+`.) |
| `DATABASE_UI_ACCENT` | No | Accent color. Default `#8c1a1b` (MIT crimson, = main_ui). |
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
   - `DATABASE_UI_PASSWORD` and `DATABASE_UI_SECRET_KEY` (secrets).
3. Generate a domain. The entrypoint fails closed if `DATABASE_UI_PASSWORD` is unset,
   so the dashboard is never exposed ungated.

## Endpoints

| Route | Purpose |
| ----- | ------- |
| `GET /` | review shell (sidebar + transcript); redirects to `/login` if not authed |
| `GET/POST /login`, `GET /logout` | shared-password gate |
| `GET /api/conversations?sort=date\|student&limit=&offset=` | list all conversations |
| `GET /api/conversation/<uuid>` | one conversation's full transcript |
| `GET /api/image/<int>` | serve an uploaded image's bytes |
| `GET /health` | liveness (open, no auth) |
