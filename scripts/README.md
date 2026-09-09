# scripts/ — container entrypoints

The three shell scripts here are the **container entrypoints** for the three
deployed Flask apps. Each Dockerfile copies one of them to `/entrypoint.sh`,
`chmod +x`es it, and sets it as the image `ENTRYPOINT` (see `Dockerfile_main`,
`Dockerfile_sandbox`, `Dockerfile_database`). On Railway, the script runs on
every deploy: it validates the environment, prepares the schema, and finally
`exec`s gunicorn to serve the app.

They are plain POSIX `sh` (not bash) so they run in the slim container image.

| Script | Serves | Default port | Schema step |
|--------|--------|--------------|-------------|
| `railway-entrypoint-main.sh` | `main_ui` (student chat) | `5001` | **Alembic migrations** (`upgrade head`) |
| `railway-entrypoint-sandbox.sh` | `sandbox_ui` (dev/TA chat) | `5000` | **`create_all` on boot** (no migrations) |
| `railway-entrypoint-database.sh` | `database_ui` (read-only review) | `5003` | **None** — never touches the schema |

## What every entrypoint does

1. **Validate required env, fail fast.** A missing required variable makes the
   script `exit 1` before gunicorn starts, so a misconfigured deploy fails
   loudly instead of booting a broken app.
2. **Normalize the Postgres URL to psycopg3.** SQLAlchemy's bare
   `postgres://` / `postgresql://` scheme defaults to psycopg2, which is **not
   installed** (requirements ship `psycopg[binary]`, i.e. psycopg3). Each script
   rewrites the scheme to `postgresql+psycopg://` so Alembic and the app don't
   crash with `ModuleNotFoundError: No module named 'psycopg2'`. Passwords are
   masked in the startup logs (`${URL%@*}@...`).
3. **Prepare the schema** — differs per app, see table above.
4. **`exec gunicorn`** with `PORT` / `WEB_CONCURRENCY` (workers, default 4) /
   `GUNICORN_TIMEOUT` (default 120s), logging access + errors to stdout/stderr.

## Per-script specifics

### `railway-entrypoint-main.sh`
- Requires **`OPENAI_API_KEY`** and **`ANTHROPIC_API_KEY`** (both providers are
  needed: RAG query-embeddings always use OpenAI `text-embedding-3-small`, and
  the Claude tutor — main_ui's default — needs Anthropic).
- Reads the database from `DATABASE_URL` (falls back to SQLite in dev, with a
  warning).
- Runs **`alembic -c main_ui/db/migrations/alembic.ini upgrade head`**; a failed
  migration aborts startup. main_ui **owns** the production `asktim` schema.

### `railway-entrypoint-sandbox.sh`
- Same two required API keys as main.
- Resolves its DB as **`SANDBOX_UI_DATABASE_URL` → `DATABASE_URL` → SQLite**
  (matching `sandbox_ui/config.py`); normalizes whichever is set. Sandbox points
  at its **own** Postgres (`asktim_test`) so test chats never interleave with
  main_ui's production data.
- **No Alembic step.** The schema is built by `Base.metadata.create_all()` inside
  `create_app()` when gunicorn imports the app; the boot steps beside it
  reconcile columns on pre-existing tables (add new model columns, drop retired
  ones).

### `railway-entrypoint-database.sh`
- **Fails closed** if `DATABASE_UI_PASSWORD` is unset — this tool exposes every
  student's conversations and uploaded images, so it refuses to start without its
  shared-password gate.
- Warns (does not fail) if `DATABASE_UI_SECRET_KEY` (session-signing key) is
  unset, so a first deploy can still boot.
- Resolves its DB as **`DATABASE_UI_DATABASE_URL` → `DATABASE_URL`** (fails if
  neither is set).
- **No migrations, no `create_all`.** It is strictly read-only; the schema is
  owned by main_ui.

## Related

- App-level env/config details: `main_ui/README.md`, `sandbox_ui/README.md`,
  `database_ui/README.md`.
- Deployment overview and the `prod-beta-plus` branch → `*-beta-plus` domain
  flow: root `README.md`.
