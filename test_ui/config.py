"""Environment-driven configuration for test_ui."""

from __future__ import annotations

import os
from dataclasses import dataclass


_DEFAULT_COOKIE_MAX_AGE_SECONDS = 180 * 24 * 3600  # 180 days


def _parse_bool(raw: str, default: bool) -> bool:
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off", ""}


@dataclass(frozen=True)
class Config:
    secret_key: str
    database_url: str
    port: int
    cookie_secure: bool
    cookie_max_age_seconds: int


def load_config() -> Config:
    secret_key = os.environ.get("TEST_UI_SECRET_KEY", "dev-insecure-key")
    # Reads the same DATABASE_URL name as main_ui. On Railway each service has
    # its own environment, so the two apps still point at separate Postgres
    # instances. The SQLite fallback stays test-specific (test_ui.db) so that
    # with DATABASE_URL UNSET locally the two apps still use different files.
    # CAUTION: if DATABASE_URL *is* set in the shared local .env, both apps use
    # it — keep test pointed at a throwaway DB when running locally.
    database_url = os.environ.get("DATABASE_URL", "sqlite:///./test_ui.db")
    port = int(os.environ.get("PORT", "5000"))
    # This is a local developer/TA tool, usually served over plain http on
    # localhost, so cookies must not require Secure by default or identity +
    # history wouldn't stick. Override with TEST_UI_COOKIE_SECURE=true behind HTTPS.
    cookie_secure = _parse_bool(os.environ.get("TEST_UI_COOKIE_SECURE"), default=False)
    cookie_max_age_seconds = int(
        os.environ.get("TEST_UI_COOKIE_MAX_AGE", str(_DEFAULT_COOKIE_MAX_AGE_SECONDS))
    )
    return Config(
        secret_key=secret_key,
        database_url=database_url,
        port=port,
        cookie_secure=cookie_secure,
        cookie_max_age_seconds=cookie_max_age_seconds,
    )
