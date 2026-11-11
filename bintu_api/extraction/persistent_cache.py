"""Perform persistent extraction-cache operations.

This module owns the timeout and failure-logging boundary for persistent
cache reads and writes. Callers supply the database functions, preserving
the established patch seams in `bintu_api.api.scrape_adapter`.
"""

from __future__ import annotations

import asyncio
import logging

from bintu_api.integrations.supabase import DATABASE_TIMEOUT_SECONDS
from bintu_api.observability import log_cache_event

logger = logging.getLogger("bintu_api.scrape")


async def read_persistent_cache(
    database_client,
    url: str,
    render_js: bool,
    include_nav: bool,
    include_header: bool,
    include_footer: bool,
    get_cached_markdown_fn,
    request_id: str | None = None,
    timeout_seconds: float = DATABASE_TIMEOUT_SECONDS,
):
    """Read a persistent cache row, returning None after a lookup failure."""
    try:
        return await asyncio.wait_for(
            get_cached_markdown_fn(
                database_client,
                url,
                render_js,
                include_nav,
                include_header,
                include_footer,
            ),
            timeout=timeout_seconds,
        )
    except Exception as error:
        logger.warning(
            "supabase_cache_lookup_failed error_type=%s",
            type(error).__name__,
        )
        return None


async def write_persistent_cache(
    database_client,
    url: str,
    render_js: bool,
    include_nav: bool,
    include_header: bool,
    include_footer: bool,
    result,
    upsert_cached_markdown_fn,
    request_id: str | None = None,
    timeout_seconds: float = DATABASE_TIMEOUT_SECONDS,
) -> None:
    """Write a persistent cache row, logging rather than raising on failure."""
    try:
        await asyncio.wait_for(
            upsert_cached_markdown_fn(
                database_client,
                url,
                render_js,
                include_nav,
                include_header,
                include_footer,
                result.markdown,
                result.truncated,
                html_tokens=result.html_tokens,
                tokens_saved_estimate=result.tokens_saved_estimate,
                limiting_factor=result.limiting_factor,
                extracted_at=result.extracted_at,
            ),
            timeout=timeout_seconds,
        )
        log_cache_event(
            event="persistent_cache_write",
            url=url,
            request_id=request_id,
            layer="persistent",
        )
    except Exception as error:
        logger.warning(
            "supabase_cache_upsert_failed error_type=%s",
            type(error).__name__,
        )
