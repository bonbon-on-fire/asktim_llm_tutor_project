"""Pure per-message token estimate for the chat composer cap.

No tokenizer is available in the repo, so this approximates: ~4 chars/token for
text (typed text + extracted attachment text) plus a flat conservative per-image
cost (~Claude's per-image maximum). Used server-side in the chat handler and
mirrored by the browser composer; keep the constants in sync with chat.js.
"""
from __future__ import annotations

CHARS_PER_TOKEN = 4
TOKENS_PER_IMAGE = 1600


def estimate_message_tokens(text: str, extracted_texts: list[str], n_images: int) -> int:
    """Estimate the token cost of one student message (text + files + images)."""
    chars = len(text or "") + sum(len(t or "") for t in (extracted_texts or []))
    text_tokens = -(-chars // CHARS_PER_TOKEN)  # ceil division
    return text_tokens + max(0, n_images) * TOKENS_PER_IMAGE
