"""Shared fetched-document and token-estimation contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class FetchedHTML:
    body: bytes
    charset: str | None
    final_url: str | None = None


def compute_approx_tokens(text: str) -> int:
    """Approximate token count: ceil(characters / 4)."""
    if not text or not text.strip():
        return 0
    return math.ceil(len(text) / 4)


def compute_tokens_saved_estimate(
    raw_html_bytes: bytes,
    extracted_text: str,
) -> int:
    """Approximate tokens saved by extraction, floored at zero."""
    html_text = raw_html_bytes.decode("utf-8", errors="replace")
    return max(
        0,
        compute_approx_tokens(html_text) - compute_approx_tokens(extracted_text),
    )