"""Build canonical extraction results from fetched documents.

This module depends only on public extraction and context APIs. It does not
import FastAPI, cache, database, robots, or network implementation details.
"""

from __future__ import annotations

from datetime import UTC, datetime

from bintu_api.context import decode_source_text
from bintu_api.database import CachedMarkdown
from bintu_api.scraper import (
    FetchedHTML,
    compute_approx_tokens,
    compute_tokens_saved_estimate,
)


def build_cached_markdown(
    document: FetchedHTML,
    extracted,
    url: str,
    *,
    extracted_at: str | None = None,
) -> CachedMarkdown:
    """Build the canonical extraction result for a freshly extracted page."""
    html_source_text = decode_source_text(document)
    html_tokens = compute_approx_tokens(html_source_text)
    tokens_saved_estimate = compute_tokens_saved_estimate(
        document.body,
        extracted.text,
    )

    return CachedMarkdown(
        markdown=extracted.text,
        truncated=extracted.truncated,
        html_tokens=html_tokens,
        tokens_saved_estimate=tokens_saved_estimate,
        limiting_factor="char_cap" if extracted.truncated else "none",
        extracted_at=extracted_at or datetime.now(UTC).isoformat(),
    )
