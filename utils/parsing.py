"""JSON parsing helpers shared across modules."""

from __future__ import annotations


def extract_json_object(text: str) -> str | None:
    """Find the first ``{`` in *text* and return the substring with balanced braces."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i, c in enumerate(text[start:], start=start):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None
