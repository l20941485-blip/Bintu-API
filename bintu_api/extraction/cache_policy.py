"""Pure cache-policy decisions for the shared extraction pipeline.

These helpers encapsulate extraction limits, persistent-cache eligibility,
credential safety, and canonical cache-key construction. They perform no I/O.
"""

from __future__ import annotations

import hashlib

from bintu_api.extraction.context import (
    DEFAULT_MAX_TEXT_CHARACTERS,
    MAX_EXTRACTION_CHARACTERS,
)
from bintu_api.security.credentials import has_credential_params
from bintu_api.settings import Settings


def resolve_extraction_cap(settings: Settings) -> int:
    """Return the effective extraction cap for a request."""
    if settings.max_text_characters == DEFAULT_MAX_TEXT_CHARACTERS:
        return MAX_EXTRACTION_CHARACTERS

    return min(settings.max_text_characters, MAX_EXTRACTION_CHARACTERS)


def is_persistent_cache_enabled(
    settings: Settings,
    links: str,
    main_content_only: bool = False,
) -> bool:
    """Return whether a response is eligible for persistent-cache reuse.


    Persistent rows share one canonical extraction policy. Custom operator caps
    use raw-HTML memory caching only. Link output changes the extracted
    Markdown, so only the default inline mode may use the existing
    persistent-cache policy until its schema is extended to store the link mode.
    """
    persistent_cache_enabled = settings.max_text_characters == DEFAULT_MAX_TEXT_CHARACTERS
    return persistent_cache_enabled and links == "inline" and not main_content_only


def is_cacheable(url: str) -> bool:
    """Return whether a URL is safe to persist in the cache."""
    return not has_credential_params(url)


def compute_cache_key(
    render_js: bool,
    links: str,
    url: str,
    *,
    include_nav: bool = False,
    include_header: bool = False,
    include_footer: bool = False,
    main_content_only: bool = False,
) -> str:
    """Compute the canonical memory-cache key for an extraction request."""
    payload = (
        f"{int(render_js)}:{links}:{url}:"
        f"{int(include_nav)}:{int(include_header)}:{int(include_footer)}:"
        f"{int(main_content_only)}"
    )
    return hashlib.sha256(payload.encode()).hexdigest()
