"""Token estimation and budget enforcement for Bintu extraction.

This module owns the canonical token approximation and the token-budget
truncation logic used across extraction and response building.

Important boundaries, invariants, or compatibility notes:
- Token counting is approximate (ceil(chars / 4)), never tokenizer-based.
- Truncation preserves Markdown structure (code fences, URLs, line/word
  boundaries) and must remain deterministic.
"""

from __future__ import annotations

import math

import re


def estimate_tokens(text: str) -> int:
    """Estimate tokens using Bintu's canonical approximation: ceil(chars /4)."""
    if not text or not text.strip():
        return 0
    return math.ceil(len(text) / 4)


def truncate_to_token_budget(text: str, max_tokens: int | None) -> tuple[str, bool]:
    """Return ``(text, truncated)`` where ``estimate_tokens(text) <= max_tokens``.

    ``max_tokens=None`` means no caller budget and returns the input unchanged.
    Truncation prefers a line boundary, then a word boundary, avoids leaving a
    dangling URL fragment, and closes a Markdown code fence it cuts through.
    """
    if max_tokens is None:
        return text, False

    if max_tokens <= 0:
        return "", bool(text)

    if estimate_tokens(text) <= max_tokens:
        return text, False

    max_chars = max_tokens * 4
    if "```" in text:
        max_chars -= 4  # Reserve room to close a fence cut by truncation.

    window = text[:max_chars]

    cut = window.rfind("\n")
    if cut < max_chars * 0.5:
        cut = max(cut, window.rfind(" "))

    if cut > 0:
        window = window[:cut]

    window = window.rstrip()
    window = re.sub(r"\((?:https?://)?[^\s)]*$", "", window).rstrip()

    if _open_fence(window):
        window = window + "\n```"

    from bintu_api.extraction.cleaner import drop_empty_fences

    window = drop_empty_fences(window)

    assert estimate_tokens(window) <= max_tokens
    return window, True


def _open_fence(text: str) -> bool:
    """True when text contains an unclosed Markdown code fence."""
    return sum(1 for line in text.split("\n") if line.startswith("```")) % 2 == 1
