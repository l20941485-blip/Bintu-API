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
        and sections is None
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
