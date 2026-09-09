"""Environment-driven configuration for main_ui."""

from __future__ import annotations

import os
from dataclasses import dataclass


_TRUTHY_WORDS = {"1", "true", "yes", "on"}
_FALSY_WORDS = {"0", "false", "no", "off", ""}


_DEFAULT_COOKIE_MAX_AGE_SECONDS = 180 * 24 * 3600  # 180 days


def _parse_bool(raw: str, default: bool) -> bool:
    """Parse an env-string as a boolean; *default* when unset, else falsy words are False."""
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
    max_message_tokens: int
    max_conversation_tokens: int
    free_messages_before_login: int
    maintenance_mode: bool
    # Deliberate exam-period lockout, scoped PER COURSE. Distinct from
    # maintenance_mode so ops can tell "closed for exams" apart from "down for
    # maintenance / real outage" (and so each shows the right wording). Unlike the
    # global maintenance flag, this locks only the chosen courses: the embed
    # overlay shows and the API 503s only for a locked course. `exam_lockdown_all`
    # captures the legacy bare-truthy value (locks every course); otherwise the
    # named slugs in `exam_lockdown_courses` are locked. Use is_exam_locked() to
    # test a course. See app_factory's gate.
    exam_lockdown_all: bool
    exam_lockdown_courses: frozenset[str]
    # Automatic outage detection (server-side, phase 2). Consecutive infra
    # failures across all students before the auto "AskTIM is down" banner
    # engages; how long a degraded state lasts before lazy expiry lets live
    # traffic re-detect; and how long each worker caches the degraded read to
    # bound DB load. See services/service_health.py.
    outage_failure_threshold: int
    outage_cooldown_seconds: int
    outage_health_cache_seconds: int
    # Hard-down provider alerting (services/provider_alerts.py). Credit/auth/
    # permission failures are human-actionable and don't self-heal, so on top of
    # the passive outage counter above they get a CRITICAL log marker and,
    # optionally, a webhook POST (None disables it) throttled to at most one
    # per this many seconds per worker.
    alert_webhook_url: str | None
    provider_alert_min_interval_seconds: int

    def is_exam_locked(self, course: str | None) -> bool:
        """True when *course* is under exam lockdown (all-courses mode, or listed)."""
        if self.exam_lockdown_all:
            return True
        return course is not None and course in self.exam_lockdown_courses


def _parse_exam_lockdown(raw: str | None) -> tuple[bool, frozenset[str]]:
    """Parse MAIN_UI_EXAM_LOCKDOWN into (lock_all, course_slugs).

    Unset or a single falsy word -> nothing locked. A single truthy word
    (``1``/``true``/``yes``/``on``) -> lock every course (back-compat with the old
    boolean). Anything else is a comma-separated list of course slugs to lock.
    """
    tokens = [t.strip() for t in (raw or "").split(",") if t.strip()]
    if not tokens:
        return False, frozenset()
    if len(tokens) == 1:
        word = tokens[0].lower()
        if word in _TRUTHY_WORDS:
            return True, frozenset()
        if word in _FALSY_WORDS:
            return False, frozenset()
    return False, frozenset(tokens)


def load_config() -> Config:
    """Build the :class:`Config` from environment variables, applying defaults."""
    secret_key = os.environ.get("MAIN_UI_SECRET_KEY", "dev-insecure-key")
    database_url = os.environ.get("DATABASE_URL", "sqlite:///./main_ui.db")
    port = int(os.environ.get("PORT", "5000"))
    cookie_secure = _parse_bool(os.environ.get("MAIN_UI_COOKIE_SECURE"), default=True)
    cookie_max_age_seconds = int(
        os.environ.get("MAIN_UI_COOKIE_MAX_AGE", str(_DEFAULT_COOKIE_MAX_AGE_SECONDS))
    )
    max_message_tokens = int(os.environ.get("MAX_MESSAGE_TOKENS", "10000"))
    max_conversation_tokens = int(os.environ.get("MAX_CONVERSATION_TOKENS", "450000"))
    free_messages_before_login = int(os.environ.get("FREE_MESSAGES_BEFORE_LOGIN", "3"))
    # Full-screen "AskTIM is down" overlay. Env-driven so it can be flipped on the
    # deployment (MAIN_UI_MAINTENANCE=1) without a code change and off again once
    # service is restored. Defaults off so normal environments are unaffected.
    maintenance_mode = _parse_bool(os.environ.get("MAIN_UI_MAINTENANCE"), default=False)
    # Full-screen "AskTIM is unavailable during exams" overlay + API lockout,
    # scoped per course. Env-driven like maintenance so it flips on the deployment
    # without a code change and off once the exam window ends. Set to a
    # comma-separated list of course slugs (e.g. MAIN_UI_EXAM_LOCKDOWN=
    # supply_chain_design) to lock only those; a bare 1/true still locks all.
    exam_lockdown_all, exam_lockdown_courses = _parse_exam_lockdown(
        os.environ.get("MAIN_UI_EXAM_LOCKDOWN")
    )
    outage_failure_threshold = int(os.environ.get("OUTAGE_FAILURE_THRESHOLD", "5"))
    outage_cooldown_seconds = int(os.environ.get("OUTAGE_COOLDOWN_SECONDS", "90"))
    outage_health_cache_seconds = int(
        os.environ.get("OUTAGE_HEALTH_CACHE_SECONDS", "5")
    )
    alert_webhook_url = os.environ.get("ALERT_WEBHOOK_URL") or None
    provider_alert_min_interval_seconds = int(
        os.environ.get("PROVIDER_ALERT_MIN_INTERVAL_SECONDS", "300")
    )
    return Config(
        secret_key=secret_key,
        database_url=database_url,
        port=port,
        cookie_secure=cookie_secure,
        cookie_max_age_seconds=cookie_max_age_seconds,
        max_message_tokens=max_message_tokens,
        max_conversation_tokens=max_conversation_tokens,
        free_messages_before_login=free_messages_before_login,
        maintenance_mode=maintenance_mode,
        exam_lockdown_all=exam_lockdown_all,
        exam_lockdown_courses=exam_lockdown_courses,
        outage_failure_threshold=outage_failure_threshold,
        outage_cooldown_seconds=outage_cooldown_seconds,
        outage_health_cache_seconds=outage_health_cache_seconds,
        alert_webhook_url=alert_webhook_url,
        provider_alert_min_interval_seconds=provider_alert_min_interval_seconds,
    )
