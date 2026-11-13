"""Decide when persistent extraction cache operations may run.

This module contains pure policy decisions only. It does not perform database
I/O, mutate caches, enforce robots rules, fetch documents, or extract text.
"""

from __future__ import annotations


def should_read_persistent_cache(
    database_client,
    persistent_cache_enabled: bool,
    cacheable: bool,
    skip_cache: bool,
    sections: list[str] | None,
) -> bool:
    """Return whether a persistent-cache read may be attempted."""
    return bool(
        database_client is not None
        and persistent_cache_enabled
        and cacheable
        and not skip_cache
    )


def should_write_persistent_cache(
    database_client,
    persistent_cache_enabled: bool,
    cacheable: bool,
    persist: bool,
) -> bool:
    """Return whether a persistent-cache write may be attempted."""
    return bool(
        database_client is not None
        and persistent_cache_enabled
        and cacheable
        and persist
    )


def should_read_memory_cache(
    skip_cache: bool,
    sections: list[str] | None,
) -> bool:
    """Return whether a memory-cache read may be attempted."""
    return not skip_cache


def should_write_memory_cache(
    cache_layer: str,
    extracted_text: str,
) -> bool:
    """Return whether a freshly fetched document should replace cached HTML."""
    return cache_layer == "none" and bool(extracted_text.strip())
