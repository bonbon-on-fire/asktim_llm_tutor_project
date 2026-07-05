"""database_ui — read-only interface for reviewing real AskTIM conversation data.

A read-only mirror of the live chat UI for browsing every conversation stored in
a Railway Postgres. One codebase, deployed twice (Sandbox DB + normal DB),
differentiated by title and color theme. See ``docs/database_ui_plan.md``.

This package NEVER writes to the database: no inserts, no schema creation, no
migrations. It only issues SELECTs.

Loads the project's ``.env`` from the repo root at import time so every
entrypoint (``python -m database_ui``, smoke tests, ``gunicorn
database_ui.run_app:app``) picks up ``DATABASE_UI_DATABASE_URL`` and friends without
manual ``$env:`` setup — mirroring ``sandbox_ui``.
"""

from __future__ import annotations

from pathlib import Path


def _load_dotenv_quietly() -> None:
    """Load the repo-root ``.env`` if python-dotenv and the file are available."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.is_file():
        load_dotenv(env_path)


_load_dotenv_quietly()
