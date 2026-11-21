"""Perform memory-cache operations for freshly fetched documents.

This module owns the memory-cache read and conditional-write boundary.
Callers supply the cache and fetch dependencies, preserving the established
patch seams in `bintu_api.api.scrape_adapter`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from bintu_api.common.fetch import FetchedHTML
from bintu_api.extraction.cache_store import CACHE_TTL


@dataclass(frozen=True)
class MemoryCacheEntry:
    """Memory-cache value preserving the original extraction timestamp."""

    document: FetchedHTML
    extracted_at: str = ""
    extractor_version: str = ""
    content_hash: str = ""


# Concurrent misses for the same key may each fetch independently and write
# the same cache key. This is intentional cache-stampede behavior; single-flight
# coalescing is deferred until duplicate-fetch cost justifies it.

def memory_cache_age_seconds(
    extracted_at: str,
    now: datetime | None = None,
) -> int | None:
    """Return whole cache age seconds, or None for an unknown timestamp."""
    if not extracted_at:
        return None

    try:
        extracted_time = datetime.fromisoformat(
            extracted_at.replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        return None

    if extracted_time.tzinfo is None:
        return None

    age = ((now or datetime.now(UTC)) - extracted_time).total_seconds()
    return 0 if age < 0 else int(age)


def is_memory_cache_fresh(
    extracted_at: str,
    now: datetime | None = None,
) -> bool:
    """Return whether a memory-cache timestamp is within the declared TTL."""
    age = memory_cache_age_seconds(extracted_at, now)
    # Legacy in-process entries created before timestamp preservation have no
    # timestamp. Treat them as fresh so a memory hit still avoids a fetch.
    return age is None or age <= int(CACHE_TTL.total_seconds())


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



def evaluate_cache_freshness(
    entry: MemoryCacheEntry,
    *,
    now: datetime,
    extractor_version: str,
) -> tuple[bool, str | None]:
    """Return (is_fresh, stale_reason) for a memory-cache entry.

    Freshness is policy-level, not proof that upstream content is unchanged:
    - Missing extracted_at -> stale (missing_timestamp).
    - Invalid extracted_at -> stale (invalid_timestamp).
    - Age beyond CACHE_TTL -> stale (ttl_expired).
    - Extractor version mismatch -> stale (extractor_version_changed).
    - Future timestamp -> treated as fresh (clock-skew tolerance).
    """
    if not entry.extracted_at:
        return False, "missing_timestamp"

    try:
        extracted_time = datetime.fromisoformat(
            entry.extracted_at.replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        return False, "invalid_timestamp"

    if extracted_time.tzinfo is None:
        return False, "invalid_timestamp"

    age = (now - extracted_time).total_seconds()
    if age < 0:
        return True, None

    if age > CACHE_TTL.total_seconds():
        return False, "ttl_expired"

    if (
        getattr(entry, "extractor_version", "")
        and entry.extractor_version != extractor_version
    ):
        return False, "extractor_version_changed"

    return True, None
