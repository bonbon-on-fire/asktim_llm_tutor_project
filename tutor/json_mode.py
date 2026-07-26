"""Structured-output enforcement for tutor replies.

The tutor must return a two-field JSON object (``pedagogical-reasoning`` and
``Student-facing-answer``). Rather than trust the model to hand-serialize valid
JSON, we enforce it at the API layer: tool-forcing on Anthropic, native
``response_format`` on OpenAI. This module is the single owner of that contract so
every code path (raw SDK, langchain streaming, langchain invoke) reads the same
schema and the same on/off gate.
"""
from __future__ import annotations

import os

TUTOR_TOOL_NAME = "tutor_reply"

_TUTOR_SCHEMA = {
    "type": "object",
    "properties": {
        "pedagogical-reasoning": {
            "type": "string",
            "description": "Hidden tutor-only reasoning; never shown to the student.",
        },
        "Student-facing-answer": {
            "type": "string",
            "description": "The reply shown to the student.",
        },
    },
    "required": ["pedagogical-reasoning", "Student-facing-answer"],
    "additionalProperties": False,
}

_JSON_MODE_FALSEY = {"0", "false", "no", "off"}


def json_mode_enabled() -> bool:
    """Enforced structured output is the DEFAULT tutor path.

    Set ``TUTOR_JSON_MODE`` to ``0``/``false``/``no``/``off`` to fall back to the
    legacy best-effort parse/repair path (instant rollback). Any other value — or
    leaving it unset — keeps enforcement on. Mirrors ``cached_history_enabled``.
    """
    return os.environ.get("TUTOR_JSON_MODE", "").strip().lower() not in _JSON_MODE_FALSEY


def anthropic_tools() -> list:
    """The single forced tutor tool, in Anthropic tool format (raw SDK + langchain)."""
    return [
        {
            "name": TUTOR_TOOL_NAME,
            "description": "Return the tutor reply as two fields.",
            "input_schema": _TUTOR_SCHEMA,
        }
    ]


def anthropic_tool_kwargs() -> dict:
    """Raw-SDK kwargs that force a single ``tutor_reply`` tool call."""
    return {
        "tools": anthropic_tools(),
        "tool_choice": {"type": "tool", "name": TUTOR_TOOL_NAME},
    }


def openai_response_format() -> dict:
    """langchain ChatOpenAI ``response_format`` for strict JSON-schema output."""
    return {
        "type": "json_schema",
        "json_schema": {
            "name": TUTOR_TOOL_NAME,
            "schema": _TUTOR_SCHEMA,
            "strict": True,
        },
    }
