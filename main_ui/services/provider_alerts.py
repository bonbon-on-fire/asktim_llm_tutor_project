"""Hard-down LLM provider classification + alerting (Tier 2).

``main_ui/routes/chat.py`` catches every tutor-stream exception generically and
folds it into the passive outage counter (``service_health.py``). That counter
is deliberately dumb about *why* a turn failed — it just counts. This module
adds a second, narrower signal on top: is the failure a **hard-down, human-
actionable** provider condition (credit/billing exhaustion, invalid auth, or a
permission/access denial) rather than a transient blip? Those conditions don't
self-heal — retrying won't fix a dead API key or an empty credit balance — so
they need a human paged, not just a banner.

Transient provider errors (rate-limit, timeout, connection, 5xx) are already
retried in ``tutor/run_tutor.py`` (``_RETRYABLE_ANTHROPIC_ERRORS``) and are
deliberately **not** classified here — anything that isn't one of the three
hard reasons below is ignored (returns ``None``).

Classification is duck-typed on the exception's class name and message text so
it works for both the Anthropic and OpenAI SDKs without a hard import of
either (and without depending on brittle ``isinstance`` checks across SDK
versions).

Alerting is two channels:

* A ``TUTOR_PROVIDER_DOWN`` CRITICAL log line — always fires, never debounced,
  so log-based alerting can key on the literal marker token.
* An optional webhook POST (plain JSON ``{"text": ...}`` via stdlib
  ``urllib.request`` — ``requests`` is not a pinned dependency), debounced per
  worker with a module-global monotonic timestamp (mirroring the
  ``_cache_expires_monotonic`` pattern in ``service_health.py``) so a burst of
  failing turns doesn't spam the channel.

Everything here is best-effort: this runs inside a live SSE stream, so nothing
it does may raise or block a student's chat turn.
"""

from __future__ import annotations

import json
import time
import urllib.request

from main_ui.config import load_config

_TIMEOUT_SECONDS = 3

_CREDIT_SUBSTRINGS = (
    "credit balance is too low",
    "insufficient_quota",
    "insufficient quota",
    "billing",
    "exceeded your current quota",
    "purchase credits",
)
_AUTH_SUBSTRINGS = (
    "invalid api key",
    "invalid x-api-key",
    "authentication",
    "could not resolve authentication",
)
_PERMISSION_SUBSTRINGS = (
    "permission",
    "do not have access",
    "not allowed to access",
)

# Per-worker debounce: suppress a second webhook POST within
# ``provider_alert_min_interval_seconds`` of the last one. Worker-local, like
# ``service_health``'s render cache; the CRITICAL log itself is never debounced.
# Sentinel is -inf (not 0.0) so the very first alert always fires even on a
# freshly-started worker whose ``time.monotonic()`` is still under the
# interval (e.g. < 300s uptime) — 0.0 would wrongly suppress that first POST.
_last_post_monotonic: float = float("-inf")


def classify_provider_outage(exc: BaseException) -> str | None:
    """Return a hard-down reason code for *exc*, or ``None`` if it isn't one.

    Reason codes: ``"credit_exhausted"``, ``"auth_invalid"``,
    ``"permission_denied"``. Duck-types on ``type(exc).__name__`` and the
    exception message so it works for both Anthropic and OpenAI SDK exceptions
    without importing either. Never raises — any unexpected error resolves to
    ``None`` so a classification bug can't break the caller.
    """
    try:
        name = type(exc).__name__
        msg = str(getattr(exc, "message", "") or exc).lower()

        if any(s in msg for s in _CREDIT_SUBSTRINGS):
            return "credit_exhausted"
        if name == "AuthenticationError" or any(s in msg for s in _AUTH_SUBSTRINGS):
            return "auth_invalid"
        if name == "PermissionDeniedError" or any(s in msg for s in _PERMISSION_SUBSTRINGS):
            return "permission_denied"
        return None
    except Exception:
        return None


def _post_webhook(url: str, message: str) -> None:
    """Fire the JSON POST. Isolated as its own seam so tests can monkeypatch it."""
    body = json.dumps({"text": message}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS)


def _reset_debounce_for_tests() -> None:
    """Reset the module-global debounce clock to its -inf sentinel. Test-only seam."""
    global _last_post_monotonic
    _last_post_monotonic = float("-inf")


def maybe_alert_provider_outage(exc: BaseException, *, logger) -> str | None:
    """Classify *exc* and, if it's hard-down, log + (maybe) webhook-alert.

    Returns the reason code (or ``None`` if *exc* isn't a hard-down provider
    failure). The CRITICAL log always fires for a classified failure; the
    webhook POST is best-effort and debounced per worker so it never blocks or
    breaks the caller — this runs inside a live SSE stream.
    """
    reason = classify_provider_outage(exc)
    if reason is None:
        return None

    # The marker fires unconditionally (never debounced) but must never raise:
    # the caller (chat.py) has no outer except around this call, inside a live
    # SSE generator, so a logging failure here would abort the stream before
    # the "error" frame is yielded.
    try:
        logger.critical("TUTOR_PROVIDER_DOWN reason=%s error=%s", reason, exc)
    except Exception:
        pass

    global _last_post_monotonic
    try:
        cfg = load_config()
        webhook_url = cfg.alert_webhook_url
        if not webhook_url:
            return reason

        min_interval = cfg.provider_alert_min_interval_seconds
        now_mono = time.monotonic()
        if now_mono - _last_post_monotonic < min_interval:
            return reason

        message = (
            f"TUTOR_PROVIDER_DOWN ({reason}): AskTIM tutor is failing — the LLM "
            "provider rejected requests. Human action required."
        )
        # Record the attempt (not the success) before firing the POST: this
        # runs on every failing turn during exactly the outage it detects, so
        # if the webhook endpoint itself is down/slow, debouncing on success
        # would re-attempt (and re-eat the 3s timeout) on every single turn.
        # A transient webhook failure just skips that one alert until the
        # next window — acceptable, since the CRITICAL log is the durable
        # signal and fires unconditionally regardless.
        _last_post_monotonic = now_mono
        _post_webhook(webhook_url, message)
    except Exception as webhook_exc:  # best-effort: never let alerting break chat
        try:
            logger.warning("provider_alerts webhook failed: %s", webhook_exc)
        except Exception:
            pass

    return reason
