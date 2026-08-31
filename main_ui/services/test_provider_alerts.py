"""Standalone: hard-down provider classification + alert debounce.

Run:
    python -m main_ui.services.test_provider_alerts

Uses a fake logger (collects .critical/.warning calls) and a monkeypatched
webhook POST seam so no real network call or sleep is needed; debounce is
exercised via the real module-global monotonic clock and reset between
scenarios with ``_reset_debounce_for_tests``.
"""
from __future__ import annotations

from main_ui.services import provider_alerts as pa


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


class _FakeLogger:
    def __init__(self):
        self.critical_calls = []
        self.warning_calls = []

    def critical(self, *args, **kwargs):
        self.critical_calls.append(args)

    def warning(self, *args, **kwargs):
        self.warning_calls.append(args)


class _FakeConfig:
    def __init__(self, alert_webhook_url=None, provider_alert_min_interval_seconds=300):
        self.alert_webhook_url = alert_webhook_url
        self.provider_alert_min_interval_seconds = provider_alert_min_interval_seconds


class CreditError(Exception):
    pass


class AuthenticationError(Exception):
    pass


class PermissionDeniedError(Exception):
    pass


def main() -> int:
    ok = True

    # --- classify_provider_outage: credit_exhausted ---
    exc1 = CreditError("Your credit balance is too low to access the Anthropic API")
    ok &= _check(
        "credit_exhausted: 'credit balance is too low' message",
        pa.classify_provider_outage(exc1) == "credit_exhausted",
        pa.classify_provider_outage(exc1),
    )
    exc2 = Exception("Error code: 429 - insufficient_quota")
    ok &= _check(
        "credit_exhausted: 'insufficient_quota' message",
        pa.classify_provider_outage(exc2) == "credit_exhausted",
        pa.classify_provider_outage(exc2),
    )

    # --- classify_provider_outage: auth_invalid ---
    exc3 = AuthenticationError("authentication failed")
    ok &= _check(
        "auth_invalid: AuthenticationError class name",
        pa.classify_provider_outage(exc3) == "auth_invalid",
        pa.classify_provider_outage(exc3),
    )
    exc4 = Exception("Invalid API Key provided")
    ok &= _check(
        "auth_invalid: 'invalid api key' message",
        pa.classify_provider_outage(exc4) == "auth_invalid",
        pa.classify_provider_outage(exc4),
    )

    # --- classify_provider_outage: permission_denied ---
    exc5 = PermissionDeniedError("you do not have access to this model")
    ok &= _check(
        "permission_denied: PermissionDeniedError class name",
        pa.classify_provider_outage(exc5) == "permission_denied",
        pa.classify_provider_outage(exc5),
    )

    # --- classify_provider_outage: None for transient/generic errors ---
    exc6 = RuntimeError("boom")
    ok &= _check(
        "None for generic RuntimeError",
        pa.classify_provider_outage(exc6) is None,
        pa.classify_provider_outage(exc6),
    )
    exc7 = TimeoutError("request timed out")
    ok &= _check(
        "None for transient TimeoutError",
        pa.classify_provider_outage(exc7) is None,
        pa.classify_provider_outage(exc7),
    )

    # --- maybe_alert_provider_outage: no webhook configured ---
    pa._reset_debounce_for_tests()
    orig_load_config = pa.load_config
    orig_post = pa._post_webhook
    posts = []

    def fake_post(url, message):
        posts.append((url, message))

    pa._post_webhook = fake_post

    try:
        pa.load_config = lambda: _FakeConfig(alert_webhook_url=None)
        logger = _FakeLogger()
        reason = pa.maybe_alert_provider_outage(exc1, logger=logger)
        ok &= _check(
            "no webhook: returns reason code",
            reason == "credit_exhausted",
            reason,
        )
        ok &= _check(
            "no webhook: logs TUTOR_PROVIDER_DOWN marker",
            len(logger.critical_calls) == 1 and "TUTOR_PROVIDER_DOWN" in logger.critical_calls[0][0],
            logger.critical_calls,
        )
        ok &= _check(
            "no webhook: does not POST",
            len(posts) == 0,
            posts,
        )

        # --- maybe_alert_provider_outage: with webhook, POSTs once, then debounced ---
        pa._reset_debounce_for_tests()
        posts.clear()
        pa.load_config = lambda: _FakeConfig(
            alert_webhook_url="https://example.invalid/hook",
            provider_alert_min_interval_seconds=300,
        )
        logger2 = _FakeLogger()
        reason2 = pa.maybe_alert_provider_outage(exc3, logger=logger2)
        ok &= _check(
            "webhook: first call posts exactly once",
            len(posts) == 1 and reason2 == "auth_invalid",
            (posts, reason2),
        )
        reason3 = pa.maybe_alert_provider_outage(exc3, logger=logger2)
        ok &= _check(
            "webhook: immediate second call is debounced (still 1 post)",
            len(posts) == 1 and reason3 == "auth_invalid",
            (posts, reason3),
        )
        ok &= _check(
            "webhook: CRITICAL log fires on every classified call (not debounced)",
            len(logger2.critical_calls) == 2,
            logger2.critical_calls,
        )

        # --- maybe_alert_provider_outage: webhook POST raises, swallowed ---
        pa._reset_debounce_for_tests()

        def raising_post(url, message):
            raise ConnectionError("network down")

        pa._post_webhook = raising_post
        logger3 = _FakeLogger()
        reason4 = None
        raised = False
        try:
            reason4 = pa.maybe_alert_provider_outage(exc5, logger=logger3)
        except Exception:
            raised = True
        ok &= _check(
            "webhook POST raising: swallowed, no exception escapes",
            raised is False,
            raised,
        )
        ok &= _check(
            "webhook POST raising: still returns reason code",
            reason4 == "permission_denied",
            reason4,
        )
        ok &= _check(
            "webhook POST raising: logs a warning",
            len(logger3.warning_calls) == 1,
            logger3.warning_calls,
        )

        # --- FIX 1 regression: logger.critical raising must not escape ---
        pa._reset_debounce_for_tests()
        posts.clear()

        class _RaisingCriticalLogger:
            def __init__(self):
                self.warning_calls = []

            def critical(self, *args, **kwargs):
                raise RuntimeError("logging backend down")

            def warning(self, *args, **kwargs):
                self.warning_calls.append(args)

        pa._post_webhook = fake_post
        raising_logger = _RaisingCriticalLogger()
        reason5 = None
        raised5 = False
        try:
            reason5 = pa.maybe_alert_provider_outage(exc1, logger=raising_logger)
        except Exception:
            raised5 = True
        ok &= _check(
            "CRITICAL log raising: swallowed, no exception escapes",
            raised5 is False,
            raised5,
        )
        ok &= _check(
            "CRITICAL log raising: still returns reason and still posts webhook",
            reason5 == "credit_exhausted" and len(posts) == 1,
            (reason5, posts),
        )

        # --- FIX 2 regression: first-ever alert must not be suppressed by a
        # low time.monotonic() reading (e.g. a freshly-started worker whose
        # uptime is under provider_alert_min_interval_seconds) ---
        pa._reset_debounce_for_tests()
        posts.clear()
        orig_monotonic = pa.time.monotonic
        pa.time.monotonic = lambda: 10.0  # well under the 300s default interval
        try:
            logger4 = _FakeLogger()
            reason6 = pa.maybe_alert_provider_outage(exc1, logger=logger4)
            ok &= _check(
                "first alert on low-uptime worker still posts (not suppressed)",
                len(posts) == 1 and reason6 == "credit_exhausted",
                (posts, reason6),
            )
        finally:
            pa.time.monotonic = orig_monotonic
    finally:
        pa.load_config = orig_load_config
        pa._post_webhook = orig_post
        pa._reset_debounce_for_tests()

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
