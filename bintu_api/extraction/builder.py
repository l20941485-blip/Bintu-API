"""Build canonical extraction results from fetched documents.

This module depends only on public extraction and context APIs. It does not
import FastAPI, cache, database, robots, or network implementation details.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from bintu_api.common.fetch import (
    FetchedHTML,
    compute_approx_tokens,
    compute_tokens_saved_estimate,
)
from bintu_api.extraction.cache_store import CachedMarkdown
from bintu_api.extraction.context import decode_source_text
from bintu_api.extraction.fingerprint import compute_content_fingerprint


def build_cached_markdown(
    document: FetchedHTML,
    extracted,
    url: str,
    *,
    extracted_at: str | None = None,
    decode_source_text_fn=None,
    content_cleaning: dict[str, Any] | None = None,
) -> CachedMarkdown:
    """Build the canonical extraction result for a freshly extracted page."""
    decode_source = decode_source_text_fn or decode_source_text
    html_source_text = decode_source(document)
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
        content_hash=hashlib.sha256(extracted.text.encode("utf-8")).hexdigest(),
        page_title=getattr(document, "page_title", None),
        page_title_source=getattr(document, "page_title_source", "none"),
        content_fingerprint=compute_content_fingerprint(extracted.text),
        content_cleaning=content_cleaning,
    )

