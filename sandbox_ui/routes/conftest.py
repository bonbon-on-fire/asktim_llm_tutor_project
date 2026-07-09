"""Pytest fixtures for sandbox_ui route tests.

Points sandbox_ui at a throwaway on-disk SQLite DB *before* importing anything
from sandbox_ui — the engine is built at import time from
``SANDBOX_UI_DATABASE_URL`` (see ``sandbox_ui/db/session.py``), so this must
run first or route tests would create tables in (and share state with) a
developer's real ``sandbox_ui.db``.
"""

from __future__ import annotations

import os
import tempfile

import pytest

_tmp_db = tempfile.NamedTemporaryFile(prefix="sandbox_ui_test_", suffix=".db", delete=False)
_tmp_db.close()
os.environ["SANDBOX_UI_DATABASE_URL"] = f"sqlite:///{_tmp_db.name}"

from sandbox_ui.run_app import app as _app  # noqa: E402 - must follow the env var above


@pytest.fixture()
def client():
    """Flask test client for the sandbox_ui app, backed by the throwaway test DB."""
    _app.config.update(TESTING=True)
    with _app.test_client() as test_client:
        yield test_client


@pytest.fixture()
def db_session():
    """A SQLAlchemy session bound to the same throwaway test DB the app uses.

    For tests that need to read back rows the app just wrote (e.g. via
    ``sandbox_ui.services.conversation``) without going through the HTTP API.
    """
    from sandbox_ui.db.session import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
