"""Perform memory-cache operations for freshly fetched documents.

This module owns the memory-cache read and conditional-write boundary.
Callers supply the cache and fetch dependencies, preserving the established
patch seams in `bintu_api.api.scrape_adapter`.
"""

from __future__ import annotations

from dataclasses import dataclass

from bintu_api.common.fetch import FetchedHTML


@dataclass(frozen=True)
class MemoryCacheEntry:
    """Memory-cache value preserving the original extraction timestamp."""

    document: FetchedHTML
    extracted_at: str = ""


# Concurrent misses for the same key may each fetch independently and write
# the same cache key. This is intentional cache-stampede behavior; single-flight
# coalescing is deferred until duplicate-fetch cost justifies it.

async def read_memory_cache(
    cache,
    cache_key: str,
    skip_cache: bool,
    sections,
) -> MemoryCacheEntry | None:
    """Read a memory-cached document and its original extraction timestamp."""
    if skip_cache:
        return None

    entry = cache.get(cache_key)
    if entry is None:
        return None

    if isinstance(entry, MemoryCacheEntry):
        return entry

    # Legacy in-process entries created before timestamp preservation.
    return MemoryCacheEntry(document=entry)


def write_memory_cache(
    cache,
    cache_key: str,
    document: FetchedHTML,
    cache_layer: str,
    extracted_text: str,
    extracted_at: str,
) -> None:
    """Replace cached HTML only after a successful, nonempty extraction."""
    if cache_layer == "none" and extracted_text.strip():
        cache.set(
            cache_key,
            MemoryCacheEntry(
                document=document,
                extracted_at=extracted_at,
            ),
        )

