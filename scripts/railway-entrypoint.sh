#!/bin/sh
set -e

echo "[startup] Validating environment..."

# Check required API keys.
# TEMPORARY: accept OPENAI_KEY as an alias for OPENAI_API_KEY (Railway var is
# currently named OPENAI_KEY). Export the canonical name so libraries that read
# OPENAI_API_KEY directly (e.g. langchain's default env lookup) still work.
if [ -z "${OPENAI_API_KEY:-}" ] && [ -n "${OPENAI_KEY:-}" ]; then
    export OPENAI_API_KEY="$OPENAI_KEY"
    echo "[startup] Using OPENAI_KEY as OPENAI_API_KEY (temporary alias)"
fi
if [ -z "${OPENAI_API_KEY:-}" ]; then
    echo "[error] OPENAI_API_KEY (or OPENAI_KEY) not set" >&2
    exit 1
fi
echo "[startup] ✓ OPENAI_API_KEY is set"

# Normalize Railway/Heroku-style Postgres URLs to the psycopg3 driver.
# SQLAlchemy's bare postgresql:// scheme defaults to psycopg2, which is NOT
# installed (requirements ships psycopg[binary] == psycopg3). The driver must
# be made explicit as postgresql+psycopg:// or both Alembic and the app crash
# with ModuleNotFoundError: No module named 'psycopg2'.
if [ -n "${DATABASE_URL:-}" ]; then
    case "$DATABASE_URL" in
        postgres://*)
            DATABASE_URL="postgresql+psycopg://${DATABASE_URL#postgres://}"
            echo "[startup] Converted DATABASE_URL postgres:// -> postgresql+psycopg://"
            ;;
        postgresql+psycopg://*)
            ;; # already explicit, leave as-is
        postgresql://*)
            DATABASE_URL="postgresql+psycopg://${DATABASE_URL#postgresql://}"
            echo "[startup] Converted DATABASE_URL postgresql:// -> postgresql+psycopg://"
            ;;
    esac
    export DATABASE_URL
    echo "[startup] ✓ DATABASE_URL is set: ${DATABASE_URL%@*}@..." # Hide password in logs
else
    echo "[startup] ⚠ DATABASE_URL not set, will use SQLite (development mode)"
fi

echo "[startup] Running database migrations..."
if ! alembic -c main_ui/db/migrations/alembic.ini upgrade head; then
    echo "[error] Database migrations failed" >&2
    exit 1
fi
echo "[startup] ✓ Database migrations completed"

PORT="${PORT:-5001}"
WEB_CONCURRENCY="${WEB_CONCURRENCY:-4}"
GUNICORN_TIMEOUT="${GUNICORN_TIMEOUT:-120}"

echo "[startup] Starting gunicorn..."
echo "[startup] - Port: $PORT"
echo "[startup] - Workers: $WEB_CONCURRENCY"
echo "[startup] - Timeout: ${GUNICORN_TIMEOUT}s"

exec gunicorn main_ui.run_app:app \
  --bind "0.0.0.0:${PORT}" \
  --workers "${WEB_CONCURRENCY}" \
  --timeout "${GUNICORN_TIMEOUT}" \
  --access-logfile - \
  --error-logfile - \
  --log-level info

