"""Environment-driven configuration for database_ui.

A single read-only dashboard for reviewing ``main_ui``'s conversation data,
styled with sandbox_ui's teal-blue accent. Env vars cover which database to read,
the title shown in the header / browser tab, and an optional accent override.
See ``docs/database_ui_plan.md``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass


_DEFAULT_COOKIE_MAX_AGE_SECONDS = 30 * 24 * 3600  # 30 days


@dataclass(frozen=True)
class Config:
    database_url: str
    title: str
    accent: str
    password: str | None
    secret_key: str
    port: int
    cookie_max_age_seconds: int
    course_passwords: dict[str, tuple[str, ...]]


def parse_course_passwords(raw: str | None) -> dict[str, tuple[str, ...]]:
    """Parse DATABASE_UI_COURSE_PASSWORDS into a ``{password: (course, ...)}`` map.

    The env value is a JSON list of ``{"password": str, "courses": [str, ...]}``
    entries. Anything malformed fails safe to an **empty** map (no course access
    granted) rather than raising — a bad config must never widen access. Entries
    missing a non-empty password or with no non-empty course keys are skipped;
    empty course strings within an entry are dropped.
    """
    if not raw or not raw.strip():
        return {}
    try:
        entries = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(entries, list):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        password = entry.get("password")
        courses = entry.get("courses")
        if not isinstance(password, str) or not password:
            continue
        if not isinstance(courses, list):
            continue
        keys = tuple(c for c in courses if isinstance(c, str) and c)
        if not keys:
            continue
        result[password] = keys
    return result


def load_config() -> Config:
    """Build the :class:`Config` from environment variables, applying defaults."""
    # Resolution order: DATABASE_UI_DATABASE_URL (explicit, wins) -> DATABASE_URL
    # (shared name; on Railway each service resolves it to its own referenced DB)
    # -> local SQLite for offline dev. For local runs against a Railway DB, point
    # DATABASE_UI_DATABASE_URL at the *public* proxy URL (DATABASE_PUBLIC_URL) — the
    # internal *.railway.internal host only resolves inside Railway.
    database_url = (
        os.environ.get("DATABASE_UI_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "sqlite:///./database_ui.db"
    )
    # Title shown in the header and the browser tab.
    title = os.environ.get("DATABASE_UI_TITLE", "AskTIM Database")
    # Match sandbox_ui's look: teal-blue accent. Override with DATABASE_UI_ACCENT if needed.
    accent = os.environ.get("DATABASE_UI_ACCENT", "#126f9a")
    # Shared-password gate. None = no gate (local dev only); deployments MUST set
    # this since the tool exposes every student's conversations and images.
    password = os.environ.get("DATABASE_UI_PASSWORD") or None
    # Per-course passwords: {password: (course_key, ...)}. Empty/malformed -> {}
    # (no course access granted; the master password still works).
    course_passwords = parse_course_passwords(
        os.environ.get("DATABASE_UI_COURSE_PASSWORDS")
    )
    secret_key = os.environ.get("DATABASE_UI_SECRET_KEY", "dev-insecure-review-key")
    port = int(os.environ.get("PORT", "5002"))
    cookie_max_age_seconds = int(
        os.environ.get("DATABASE_UI_COOKIE_MAX_AGE", str(_DEFAULT_COOKIE_MAX_AGE_SECONDS))
    )
    return Config(
        database_url=database_url,
        title=title,
        accent=accent,
        password=password,
        secret_key=secret_key,
        port=port,
        cookie_max_age_seconds=cookie_max_age_seconds,
        course_passwords=course_passwords,
    )
