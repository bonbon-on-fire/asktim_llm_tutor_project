"""Environment-driven configuration for main_ui."""

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
    secret_key = os.environ.get("MAIN_UI_SECRET_KEY", "dev-insecure-key")
    database_url = os.environ.get("DATABASE_URL", "sqlite:///./main_ui.db")
    port = int(os.environ.get("PORT", "5001"))
    cookie_secure = _parse_bool(os.environ.get("MAIN_UI_COOKIE_SECURE"), default=True)
    cookie_max_age_seconds = int(
        os.environ.get("MAIN_UI_COOKIE_MAX_AGE", str(_DEFAULT_COOKIE_MAX_AGE_SECONDS))
    )
    return Config(
        secret_key=secret_key,
        database_url=database_url,
        port=port,
        cookie_secure=cookie_secure,
        cookie_max_age_seconds=cookie_max_age_seconds,
    )
