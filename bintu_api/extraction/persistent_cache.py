"""Perform persistent extraction-cache operations.

This module owns the timeout and failure-logging boundary for persistent
cache reads and writes. Callers supply the database functions, preserving
the established patch seams in `bintu_api.api.scrape_adapter`.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from bintu_api.integrations.supabase import DATABASE_TIMEOUT_SECONDS
from bintu_api.observability import log_cache_event

logger = logging.getLogger("bintu_api.scrape")

@dataclass
class PersistentCacheCircuitBreaker:
    """Stop repeated persistent-cache operations after consecutive failures."""

    failure_threshold: int = 3
    cooldown_seconds: float = 60.0

    def __post_init__(self) -> None:
        self._failure_count = 0
        self._open_until = 0.0

    def should_allow(self) -> bool:
        """Return whether a persistent-cache operation may be attempted."""
        return time.monotonic() >= self._open_until

    def is_open(self) -> bool:
        """Return whether the breaker is currently open."""
        return time.monotonic() < self._open_until

    def record_failure(self) -> None:
        """Record a failure and open the breaker after the configured threshold."""
        self._failure_count += 1
        if self._failure_count >= self.failure_threshold:
            self._open_until = time.monotonic() + self.cooldown_seconds

    def record_success(self) -> None:
        """Reset failure tracking after a successful operation."""
        self._failure_count = 0
        self._open_until = 0.0


def _safe_error_details(error: Exception) -> tuple[str, str]:
    """Extract non-sensitive diagnostic fields from a cache integration error."""
    error_code = getattr(error, "code", None)
    error_message = getattr(error, "message", None)

    if not isinstance(error_code, str) or not error_code:
        error_code = ""

    if not isinstance(error_message, str) or not error_message:
        error_message = str(error)

    return error_code, error_message




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
    circuit_breaker: PersistentCacheCircuitBreaker | None = None,
):
    """Read a persistent cache row, returning None after a lookup failure."""
    if circuit_breaker is not None and not circuit_breaker.should_allow():
        return None

    try:
        result = await asyncio.wait_for(
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
        if circuit_breaker is not None:
            circuit_breaker.record_success()
        return result
    except Exception as error:
        if circuit_breaker is not None:
            circuit_breaker.record_failure()
        error_code, error_message = _safe_error_details(error)
        logger.warning(
            "supabase_cache_lookup_failed error_type=%s error_code=%s "
            "error_message=%s request_id=%s",
            type(error).__name__,
            error_code,
            error_message,
            request_id,
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
    circuit_breaker: PersistentCacheCircuitBreaker | None = None,
) -> None:
    """Write a persistent cache row, logging rather than raising on failure."""
    if circuit_breaker is not None and not circuit_breaker.should_allow():
        return

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
                page_title=result.page_title,
                content_fingerprint=result.content_fingerprint,
                content_cleaning=result.content_cleaning,
            ),
            timeout=timeout_seconds,
        )
        if circuit_breaker is not None:
            circuit_breaker.record_success()
        log_cache_event(
            event="persistent_cache_write",
            url=url,
            request_id=request_id,
            layer="persistent",
        )
    except Exception as error:
        if circuit_breaker is not None:
            circuit_breaker.record_failure()
        error_code, error_message = _safe_error_details(error)
        logger.warning(
            "supabase_cache_upsert_failed error_type=%s error_code=%s "
            "error_message=%s request_id=%s",
            type(error).__name__,
            error_code,
            error_message,
            request_id,
        )
