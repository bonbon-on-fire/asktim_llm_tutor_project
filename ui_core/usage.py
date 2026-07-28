"""Pure helpers for reading a tutor message's stored usage / retrieval JSON.

Two dependency-light functions shared by every reader of the ``messages`` table:
the live apps' ``ui_core.services.conversation`` and the ``database_ui`` review
dashboard (which keeps its own dependency-minimal service — it can't import
``ui_core.services.conversation``, since that pulls in ``tutor``, which isn't in
database_ui's image). Keeping the parsing here means one implementation for both.
"""

from __future__ import annotations

import json


def model_from_usage_json(usage_json: str | None) -> str | None:
    """Pull the ``model`` id out of a tutor message's stored usage breakdown.

    ``usage_json`` is the JSON written alongside ``cost_usd`` (model id + token
    counts). Returns ``None`` for a missing, empty, or unparseable value so the
    UI can fall back gracefully.
    """
    if not usage_json:
        return None
    try:
        return (json.loads(usage_json) or {}).get("model")
    except (ValueError, TypeError):
        return None


def new_tokens_from_usage_json(usage_json: str | None) -> int:
    """Cost-relevant ("new", non-cached) token count for one stored turn.

    ``usage_json`` is the tutor turn's cost dict as emitted by the bridge, where
    each per-call record sits at the **top level** keyed by call name::

        {"model": ..., "usd": ..., "tutor": {input_tokens, output_tokens,
         cache_read, ...}, "embedding": {...}}

    (A legacy ``{"calls": {name: {...}}}`` wrapper is also accepted.) Per call,
    new tokens = ``max(0, input_tokens - cache_read) + output_tokens``; summed
    across calls. Scalar top-level fields (``model``, ``usd``) and any dict that
    carries neither ``input_tokens`` nor ``output_tokens`` are ignored, so only
    real call records count. Returns 0 for a missing, empty, unparseable, or
    shape-unexpected value so a bad row never blocks a chat.
    """
    if not usage_json:
        return 0
    try:
        data = json.loads(usage_json)
    except (ValueError, TypeError):
        return 0
    if not isinstance(data, dict):
        return 0
    calls = data.get("calls")
    # Real bridge output keys call records at the top level; the legacy
    # ``{"calls": {...}}`` shape nests them one level down.
    call_records = calls.values() if isinstance(calls, dict) else data.values()
    total = 0
    for call in call_records:
        if not isinstance(call, dict):
            continue
        inp = call.get("input_tokens")
        out = call.get("output_tokens")
        if inp is None and out is None:
            # Not a call record (e.g. a nested config/metadata dict).
            continue
        cache = call.get("cache_read") or 0
        total += max(0, (inp or 0) - cache) + (out or 0)
    return total


def records_from_retrieved_context(retrieved_context: str | None) -> list:
    """Parse a tutor message's ``retrieved_context`` JSON into a list of records.

    Each record is a ``{source, score, chars, text}`` chunk. Returns ``[]`` for a
    missing, empty, unparseable, or non-list value.
    """
    if not retrieved_context:
        return []
    try:
        records = json.loads(retrieved_context)
    except (ValueError, TypeError):
        return []
    return records if isinstance(records, list) else []
