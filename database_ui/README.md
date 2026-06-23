# database_ui

**🔗 Live: <https://asktim-database.up.railway.app/>** (password-gated)

A **read-only** dashboard for reviewing real AskTIM conversation data. It looks
like the `main_ui` chat UI (same MIT-crimson styling) but strips every input
affordance — there is no composer, no "new chat", no writes of any kind. It
lists **all** conversations in the database (across every student) and renders a
selected one's full transcript, including the tutor's pedagogical reasoning and
any uploaded images.

Built to review **`main_ui`**'s production database. See the full design +
checklist in [`PLANNING.md`](PLANNING.md).

## Read-only by construction

- The models map only the columns shared by `main_ui` and `sandbox_ui`, so the same
  code reads either DB unchanged.
- No `create_all`, no migrations. The session always rolls back, never commits.
- Every route is behind a shared-password gate; the API endpoints intentionally
  drop the per-viewer ownership checks the live apps use (review sees everyone).

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
| `DATABASE_UI_TITLE` | No | Header + tab title. Default `AskTIM · Database Beta`. |
| `DATABASE_UI_ACCENT` | No | Accent color. Default `#8c1a1b` (MIT crimson, = main_ui). |
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
