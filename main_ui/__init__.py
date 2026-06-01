"""main_ui — production-shape embeddable tutor app.

Loads the project's `.env` from the repo root at package import time so every
entrypoint (`python -m main_ui`, smoke tests, `gunicorn main_ui.run_app:app`)
picks up `OPENAI_API_KEY` and friends without manual `$env:` setup. This is a
deliberate localized exception to the Phase 2/5 cleanups that pulled
`.env` loading out of `tutor/`, `judge/`, and `test_ui/`.
"""

from __future__ import annotations

from pathlib import Path


def _load_dotenv_quietly() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if env_path.is_file():
        load_dotenv(env_path)


_load_dotenv_quietly()
