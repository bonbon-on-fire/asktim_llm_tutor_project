"""Standalone: main_ui config exposes env-tunable caps with locked defaults.

Run:
    python -m main_ui.test_config_limits
"""
from __future__ import annotations

import os
from main_ui.config import load_config


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    for k in ("MAX_MESSAGE_TOKENS", "MAX_CONVERSATION_TOKENS", "FREE_MESSAGES_BEFORE_LOGIN"):
        os.environ.pop(k, None)
    c = load_config()
    ok &= _check("default max_message_tokens", c.max_message_tokens == 10000, c.max_message_tokens)
    ok &= _check("default max_conversation_tokens", c.max_conversation_tokens == 225000, c.max_conversation_tokens)
    ok &= _check("default free_messages_before_login", c.free_messages_before_login == 3, c.free_messages_before_login)

    os.environ["MAX_MESSAGE_TOKENS"] = "5000"
    os.environ["MAX_CONVERSATION_TOKENS"] = "100000"
    os.environ["FREE_MESSAGES_BEFORE_LOGIN"] = "1"
    c = load_config()
    ok &= _check("env override max_message_tokens", c.max_message_tokens == 5000, c.max_message_tokens)
    ok &= _check("env override max_conversation_tokens", c.max_conversation_tokens == 100000, c.max_conversation_tokens)
    ok &= _check("env override free_messages_before_login", c.free_messages_before_login == 1, c.free_messages_before_login)
    for k in ("MAX_MESSAGE_TOKENS", "MAX_CONVERSATION_TOKENS", "FREE_MESSAGES_BEFORE_LOGIN"):
        os.environ.pop(k, None)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
