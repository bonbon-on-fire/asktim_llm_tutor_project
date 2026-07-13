#!/bin/sh
set -e

echo "[startup] Validating environment..."

# Check required API keys. Both providers are required: RAG query-embeddings
# always use OpenAI (text-embedding-3-small) and the tutor may run on GPT
# (sandbox's default), while the Claude tutor option needs Anthropic. This is an
# internal project, so Railway sets the plain standard names per service.
if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "[error] OPENAI_API_KEY not set" >&2
    exit 1
fi
echo "[startup] ✓ OPENAI_API_KEY is set"
if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "[error] ANTHROPIC_API_KEY not set" >&2
    exit 1
fi
echo "[startup] ✓ ANTHROPIC_API_KEY is set"

# Normalize a Railway/Heroku-style Postgres URL to the psycopg3 driver.
# SQLAlchemy's bare postgres:// / postgresql:// scheme defaults to psycopg2,
# which is NOT installed (requirements ships psycopg[binary] == psycopg3). The
# driver must be made explicit as postgresql+psycopg:// or the app crashes on
# boot with ModuleNotFoundError: No module named 'psycopg2' — and data never
# lands in Postgres.
normalize_pg() {
    case "$1" in
        postgres://*)   printf 'postgresql+psycopg://%s' "${1#postgres://}" ;;
        postgresql://*) printf 'postgresql+psycopg://%s' "${1#postgresql://}" ;;
        *)              printf '%s' "$1" ;; # already explicit (or sqlite) — leave as-is
    esac
}

# sandbox_ui resolves its database as SANDBOX_UI_DATABASE_URL -> DATABASE_URL -> SQLite
# (see sandbox_ui/config.py). On Railway the test service references its own Postgres
# via DATABASE_URL. Normalize whichever is set so the effective URL the app picks
# is already psycopg3-ready before gunicorn imports sandbox_ui.run_app:app.
if [ -n "${SANDBOX_UI_DATABASE_URL:-}" ]; then
    SANDBOX_UI_DATABASE_URL="$(normalize_pg "$SANDBOX_UI_DATABASE_URL")"
    export SANDBOX_UI_DATABASE_URL
    echo "[startup] ✓ SANDBOX_UI_DATABASE_URL is set: ${SANDBOX_UI_DATABASE_URL%@*}@..." # Hide host in logs
fi
if [ -n "${DATABASE_URL:-}" ]; then
    DATABASE_URL="$(normalize_pg "$DATABASE_URL")"
    export DATABASE_URL
    echo "[startup] ✓ DATABASE_URL is set: ${DATABASE_URL%@*}@..." # Hide host in logs
fi
if [ -z "${SANDBOX_UI_DATABASE_URL:-}" ] && [ -z "${DATABASE_URL:-}" ]; then
    echo "[startup] ⚠ No database URL set, will use SQLite (development mode — data is ephemeral)"
fi

# No Alembic step for sandbox_ui: the schema is built by Base.metadata.create_all()
# inside create_app(), which runs when gunicorn imports sandbox_ui.run_app:app.
# The target Postgres just needs to exist and be the Sandbox's OWN empty DB
# (main_ui's schema lacks sandbox_ui's syllabus_enabled/custom_* columns, and
# create_all only creates missing tables, never adds columns to existing ones).
echo "[startup] Schema is created on boot via create_all (no migration step)"

PORT="${PORT:-5000}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-4}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-120}"

echo "[startup] Starting gunicorn..."
echo "[startup] - Port: $PORT"
echo "[startup] - Workers: $WEB_CONCURRENCY"
echo "[startup] - Timeout: ${GUNICORN_TIMEOUT}s"

exec gunicorn sandbox_ui.run_app:app \
  --bind "0.0.0.0:${PORT}" \
  --workers "${WEB_CONCURRENCY}" \
  --timeout "${GUNICORN_TIMEOUT}" \
  --access-logfile - \
  --error-logfile - \
  --log-level info
