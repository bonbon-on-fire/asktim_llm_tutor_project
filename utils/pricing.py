"""Best-effort token-cost estimation for model calls.

Token **counts** are exact (read from LangChain ``usage_metadata``); only the $
conversion uses the rate table below. Rates are US dollars per 1,000,000 tokens.

Rates verified against published pricing (2026-07). Override any rate without
editing code via an env var of the form ``PRICE_<MODEL>_<KEY>`` (``-`` and ``.``
become ``_``, upper-cased), e.g.::

    PRICE_CLAUDE_SONNET_4_6_INPUT=3.0
    PRICE_GPT_5_4_OUTPUT=15.0

``cache_read`` / ``cache_write`` apply to prompt caching. On Anthropic the tutor's
cached system prompt bills cache reads at 0.1x input and cache writes at 1.25x
input for the default 5-minute ephemeral cache (a 1-hour TTL would be 2x input =
6.00 for sonnet-4-6; the tutor uses the 5m default). On OpenAI, cached prompt
prefixes bill at ``cache_read``; there is no separate write premium. When a rate
is absent the input rate is used.
"""

from __future__ import annotations

import os
import re

# $ / 1,000,000 tokens. Verified 2026-07 against published pricing:
#   claude-sonnet-5   — Anthropic ($3 in / $15 out; cache read 0.1x, write 1.25x).
#                       Intro pricing is $2/$10 through 2026-08-31 — set
#                       PRICE_CLAUDE_SONNET_5_INPUT / _OUTPUT to use it. Sticker
#                       rates here so estimates don't under-count after the intro.
#   claude-sonnet-4-6 — Anthropic ($3 in / $15 out; cache read 0.1x, write 1.25x)
#   gpt-5.4           — OpenAI ($2.50 in / $15 out; cached input $0.25)
#   text-embedding-3-small — OpenAI ($0.02)
_DEFAULT_RATES: dict[str, dict[str, float]] = {
    "text-embedding-3-small": {"input": 0.02, "output": 0.0},
    "gpt-5.4": {"input": 2.50, "output": 15.0, "cache_read": 0.25},
    "claude-sonnet-5": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,   # 0.1x input
        "cache_write": 3.75,  # 1.25x input (5-minute ephemeral, the default)
    },
    "claude-sonnet-4-6": {
        "input": 3.0,
        "output": 15.0,
        "cache_read": 0.30,   # 0.1x input
        "cache_write": 3.75,  # 1.25x input (5-minute ephemeral, the default)
    },
}

# Models whose default rates are unverified guesses (surfaced in output notes).
# Empty now that all three models' rates are verified against published pricing.
PLACEHOLDER_MODELS: set[str] = set()

# Providers report date-stamped ids (``gpt-5.4-2026-03-05``, ``claude-...-20251114``);
# strip a trailing ``-YYYY-MM-DD`` or ``-YYYYMMDD`` to reach the base rate key.
_DATE_SUFFIX = re.compile(r"-(?:\d{4}-\d{2}-\d{2}|\d{8})$")


def _resolve_model(model: str) -> str:
    """Map a possibly date-stamped model id to a known rate-table key."""
    if model in _DEFAULT_RATES:
        return model
    base = _DATE_SUFFIX.sub("", model)
    if base in _DEFAULT_RATES:
        return base
    matches = [k for k in _DEFAULT_RATES if base.startswith(k)]
    return max(matches, key=len) if matches else model


def _env_key(model: str, key: str) -> str:
    """Return the ``PRICE_<MODEL>_<KEY>`` env var name for a model/rate-key pair."""
    return "PRICE_" + model.upper().replace("-", "_").replace(".", "_") + "_" + key.upper()


def rate(model: str, key: str, default: float = 0.0) -> float:
    """Return the $/1M rate for *model*/*key*, honoring a ``PRICE_*`` env override.

    Date-stamped model ids are normalized to their base rate key first.
    """
    model = _resolve_model(model)
    env = os.environ.get(_env_key(model, key))
    if env:
        try:
            return float(env)
        except ValueError:
            pass
    return _DEFAULT_RATES.get(model, {}).get(key, default)


def estimate_cost_usd(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read: int = 0,
    cache_write: int = 0,
) -> float:
    """Estimate the USD cost of one call from its token counts.

    Cache-aware: ``input_tokens`` is treated as the full prompt size, of which
    ``cache_read`` was served from cache and ``cache_write`` was written to it;
    the remainder is billed at the normal input rate.
    """
    in_rate = rate(model, "input")
    out_rate = rate(model, "output")
    cr_rate = rate(model, "cache_read", in_rate)
    cw_rate = rate(model, "cache_write", in_rate)
    non_cached = max(0, input_tokens - cache_read - cache_write)
    total = (
        non_cached * in_rate
        + cache_read * cr_rate
        + cache_write * cw_rate
        + output_tokens * out_rate
    )
    return total / 1_000_000


def usage_from_message(msg) -> dict:
    """Extract a normalized usage dict from a LangChain message's ``usage_metadata``.

    Returns zeros when the provider/message didn't report usage (e.g. a
    sanitized fallback message), so cost degrades to 0 for that call rather
    than crashing.
    """
    um = getattr(msg, "usage_metadata", None) or {}
    itd = um.get("input_token_details") or {}
    # langchain-anthropic reports "cache_creation" as 0 and breaks cache writes out
    # by TTL (ephemeral_5m / ephemeral_1h); sum those when cache_creation is unset.
    # ``input_tokens`` already includes cache read + write, so the cost formula
    # subtracts them to recover the full-price remainder.
    cache_write = int(itd.get("cache_creation", 0) or 0) or (
        int(itd.get("ephemeral_5m_input_tokens", 0) or 0)
        + int(itd.get("ephemeral_1h_input_tokens", 0) or 0)
    )
    return {
        "input_tokens": int(um.get("input_tokens", 0) or 0),
        "output_tokens": int(um.get("output_tokens", 0) or 0),
        "cache_read": int(itd.get("cache_read", 0) or 0),
        "cache_write": cache_write,
    }


def model_from_message(msg, fallback: str) -> str:
    """Return the actual model id from a message's ``response_metadata``, else *fallback*."""
    rm = getattr(msg, "response_metadata", None) or {}
    return rm.get("model_name") or rm.get("model") or fallback


def priced(model: str, usage: dict) -> dict:
    """Bundle a usage dict with its model, USD cost, and a placeholder flag."""
    usd = estimate_cost_usd(model, **usage)
    return {
        "model": model,
        **usage,
        "usd": round(usd, 6),
        "rate_is_placeholder": _resolve_model(model) in PLACEHOLDER_MODELS,
    }
