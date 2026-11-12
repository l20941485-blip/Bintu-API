"""Perform memory-cache operations for freshly fetched documents.

This module owns the memory-cache read and conditional-write boundary.
Callers supply the cache and fetch dependencies, preserving the established
patch seams in `bintu_api.api.scrape_adapter`.
"""

from __future__ import annotations

from bintu_api.common.fetch import FetchedHTML

# Concurrent misses for the same key may each fetch independently and write
# the same cache key. This is intentional cache-stampede behavior; single-flight
# coalescing is deferred until duplicate-fetch cost justifies it.

async def read_memory_cache(cache, cache_key: str, skip_cache: bool, sections):
    """Read a document from memory cache when permitted."""
    if skip_cache or sections is not None:
        return None
    return cache.get(cache_key)


def write_memory_cache(
    cache,
    cache_key: str,
    document: FetchedHTML,
    cache_layer: str,
    extracted_text: str,
) -> None:
    """Replace cached HTML only after a successful, nonempty extraction."""
    if cache_layer == "none" and extracted_text.strip():
        cache.set(cache_key, document)

