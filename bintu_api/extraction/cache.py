"""Cache-economics helpers for extraction results.

This module keeps persisted cache savings and provenance-sensitive metadata in a
single place so the REST and MCP surfaces preserve the same economics without
duplicating logic. It owns the compatibility contract for cached extraction
results: when the original HTML is no longer available, the module reuses the
persisted economics instead of recomputing a misleading zero-savings baseline.
"""

from __future__ import annotations

from bintu_api.extraction.context import CacheEconomics
from bintu_api.database import CachedMarkdown
from bintu_api.scraper import FetchedHTML, _compute_tokens_saved_estimate

__all__ = [
    "build_cache_economics",
    "compute_saved_tokens",
]


def build_cache_economics(document: FetchedHTML | None, cached: CachedMarkdown, cache_layer: str) -> CacheEconomics | None:
    """Return the original extraction economics for persistent-cache hits."""
    if cache_layer != "persistent":
        return None
    return CacheEconomics(
        html_tokens=cached.html_tokens,
        tokens_saved_estimate=cached.tokens_saved_estimate,
        limiting_factor=cached.limiting_factor,
        truncated=cached.truncated,
        extracted_at=cached.extracted_at,
    )


def compute_saved_tokens(document: FetchedHTML | None, cached: CachedMarkdown, cache_layer: str) -> int:
    """Preserve the pre-cache savings logic used by REST and MCP responses."""
    if cache_layer == "persistent" and cached.tokens_saved_estimate > 0:
        return cached.tokens_saved_estimate
    if document is not None:
        return _compute_tokens_saved_estimate(document.body, cached.markdown)
    return 0


