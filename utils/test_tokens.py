"""Standalone: per-message token estimate (text + files + images).

Run:
    python -m utils.test_tokens
"""
from __future__ import annotations

from utils.tokens import estimate_message_tokens, CHARS_PER_TOKEN, TOKENS_PER_IMAGE


def _check(label, ok, detail=""):
    print(("PASS" if ok else "FAIL"), "-", label, ("" if ok else f":: {detail}"))
    return ok


def main() -> int:
    ok = True
    ok &= _check("empty -> 0", estimate_message_tokens("", [], 0) == 0)
    ok &= _check("text ceil-div", estimate_message_tokens("a" * 9, [], 0) == 3, estimate_message_tokens("a" * 9, [], 0))  # ceil(9/4)=3
    ok &= _check("one image", estimate_message_tokens("", [], 1) == TOKENS_PER_IMAGE)
    ok &= _check("three images", estimate_message_tokens("", [], 3) == 3 * TOKENS_PER_IMAGE)
    ok &= _check(
        "mixed text+files+images",
        estimate_message_tokens("x" * 400, ["y" * 400], 2)
        == (800 // CHARS_PER_TOKEN) + 2 * TOKENS_PER_IMAGE,
        estimate_message_tokens("x" * 400, ["y" * 400], 2),
    )
    # A maxed legit message stays under 10k; a huge paste exceeds it.
    ok &= _check("maxed legit < 10k", estimate_message_tokens("t" * 4000, ["f" * 15000], 3) < 10000,
                 estimate_message_tokens("t" * 4000, ["f" * 15000], 3))
    ok &= _check("50k-char paste >= 10k", estimate_message_tokens("z" * 50000, [], 0) >= 10000,
                 estimate_message_tokens("z" * 50000, [], 0))
    ok &= _check("None-safe", estimate_message_tokens(None, [None], 0) == 0)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
