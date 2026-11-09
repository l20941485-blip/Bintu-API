"""Token-economics helpers shared by extraction and response shaping."""

from __future__ import annotations

__all__ = ["delivered_savings"]


def delivered_savings(html_tokens: int, delivered_tokens: int) -> int:
    """Tokens saved for this response: source HTML estimate minus delivered text."""
    return max(0, int(html_tokens) - int(delivered_tokens))
