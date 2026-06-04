#!/bin/sh
set -e

echo "[startup] Validating environment..."

# Check required API keys
if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "[error] OPENAI_API_KEY not set" >&2
    exit 1
fi
echo "[startup] ✓ OPENAI_API_KEY is set"

# test_ui resolves its DB the same way config.py does: TEST_UI_DATABASE_URL
# (explicit, wins) -> DATABASE_URL (shared name; Railway gives each service its
# own env, so it still resolves to a separate Postgres) -> SQLite fallback.
# Normalize whichever one is in effect to the psycopg3 driver — the app ships
# psycopg[binary] (psycopg3), so a bare postgresql:// (which SQLAlchemy maps to
# psycopg2) would crash with ModuleNotFoundError: No module named 'psycopg2'.
normalize_pg_url() {
    case "$1" in
        postgres://*) echo "postgresql+psycopg://${1#postgres://}" ;;
        postgresql://*) echo "postgresql+psycopg://${1#postgresql://}" ;;
        *) echo "$1" ;; # already postgresql+psycopg:// or non-postgres — leave as-is
    esac
}

if [ -n "${TEST_UI_DATABASE_URL:-}" ]; then
    TEST_UI_DATABASE_URL="$(normalize_pg_url "$TEST_UI_DATABASE_URL")"
    export TEST_UI_DATABASE_URL
    echo "[startup] ✓ TEST_UI_DATABASE_URL is set: ${TEST_UI_DATABASE_URL%@*}@..." # Hide password in logs
elif [ -n "${DATABASE_URL:-}" ]; then
    DATABASE_URL="$(normalize_pg_url "$DATABASE_URL")"
    export DATABASE_URL
    echo "[startup] ✓ DATABASE_URL is set: ${DATABASE_URL%@*}@..." # Hide password in logs
else
    echo "[startup] ⚠ Neither TEST_UI_DATABASE_URL nor DATABASE_URL set, will use SQLite (development mode)"
fi

# test_ui builds its schema with Base.metadata.create_all on boot (no Alembic),
# so there is no separate migration step here — the database just needs to exist.

PORT="${PORT:-5000}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-4}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-120}"

echo "[startup] Starting gunicorn (test_ui)..."
echo "[startup] - Port: $PORT"
echo "[startup] - Workers: $WEB_CONCURRENCY"
echo "[startup] - Timeout: ${GUNICORN_TIMEOUT}s"

exec gunicorn test_ui.run_app:app \
  --bind "0.0.0.0:${PORT}" \
  --workers "${WEB_CONCURRENCY}" \
  --timeout "${GUNICORN_TIMEOUT}" \
  --access-logfile - \
  --error-logfile - \
  --log-level info
