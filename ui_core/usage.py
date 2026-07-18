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
