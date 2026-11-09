"""Shared fetch, robots, cache, and provenance helpers for API routes.

This module owns the fetch -> robots -> cache -> extract boundary shared by
the REST scrape and chunk endpoints, plus the URL redaction and provenance
helpers used to build responses.

Important boundaries, invariants, or compatibility notes:
- Never performs metering or MCP JSON-RPC formatting.
- Preserves the exact cache economics and SSRF/robots behavior of routes.py.
- sanitize_url and credential redaction delegate to the security package.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

from fastapi import Request

from bintu_api.auth import has_valid_proxy_secret as has_valid_proxy_secret
from bintu_api.auth import rate_limit_identity as rate_limit_identity
from bintu_api.auth import verify_api_access as verify_api_access
from bintu_api.database import (
    DATABASE_TIMEOUT_SECONDS,
    CachedMarkdown,
    get_cached_markdown,
    upsert_cached_markdown,
)
from bintu_api.extraction.builder import build_cached_markdown
from bintu_api.extraction.cache_policy import (
    compute_cache_key,
    is_cacheable,
    is_persistent_cache_enabled,
    resolve_extraction_cap,
)
from bintu_api.extraction.cacheaccess import (
    should_read_memory_cache,
    should_read_persistent_cache,
    should_write_memory_cache,
    should_write_persistent_cache,
)
from bintu_api.extraction.context import _decode_source_text
from bintu_api.extraction.output import (  # noqa: F401
    TOKEN_METHOD,
    redact_cache_url,
)
from bintu_api.extraction.output import (
    build_provenance as _build_provenance,  # noqa: F401
)
from bintu_api.extraction.output import (
    build_scrape_response as _build_response,  # noqa: F401
)
from bintu_api.extraction.output import (
    is_sensitive_query_parameter as _is_sensitive_query_parameter,  # noqa: F401
)
from bintu_api.extraction.request_policy import (
    resolve_fetch_strategy,
    validate_link_mode,
)
from bintu_api.observability import log_cache_event
from bintu_api.robots import robots_decision as robots_decision
from bintu_api.robots import robots_mode as robots_mode
from bintu_api.scraper import (
    FetchedHTML,
    extract_text_result,
    fetch_html_document,
    fetch_rendered_html_document,
)
from bintu_api.settings import Settings

logger = logging.getLogger("bintu_api.scrape")

LINK_MODES = ("inline", "footnotes", "false")


async def _enforce_robots(
    url: str,
    settings: Settings,
    url_hash: str,
) -> None:
    """Compatibility delegate preserving the established robots patch seam."""
    from bintu_api.security.robots_policy import enforce_robots

    return await enforce_robots(
        url,
        settings,
        url_hash,
        robots_mode_fn=robots_mode,
        robots_decision_fn=robots_decision,
    )

async def _scrape_text(*args, **kwargs):
    """Compatibility delegate for the route-level text extraction helper."""
    from bintu_api.api.routes.extract import _scrape_text as implementation

    return await implementation(*args, **kwargs)

async def _fetch_and_extract(
    request: Request,
    url: str,
    *,
    include_nav: bool,
    include_header: bool,
    include_footer: bool,
    render_js: bool,
    links: Literal["inline", "footnotes", "false"] = "inline",
    skip_cache: bool = False,
    persist: bool = True,
    mode: str = "scrape",
    max_tokens: int = 6000,
    footnote_url_policy: Literal["full", "truncated"] = "truncated",
    max_footnote_url_length: int = 100,
    sections: list[str] | None = None,
) -> tuple[FetchedHTML | None, CachedMarkdown, str]:
    """Shared fetch -> robots -> cache -> extract boundary for REST and MCP.


    Returns:
        document: FetchedHTML for a fresh fetch; None for a cache hit.
        result: extracted markdown, truncation flag, and extraction economics.
        cache_layer: "none", "memory", or "persistent".


    Raises the same HTTPException and scraper exceptions as the REST endpoint.
    """
    validate_link_mode(links)

    settings = request.app.state.settings
    extraction_cap = resolve_extraction_cap(settings)
    persistent_cache_enabled = is_persistent_cache_enabled(settings, links)
    cacheable = is_cacheable(url)
    database_client = getattr(request.app.state, "supabase_client", None)
    result: CachedMarkdown | None = None
    document: FetchedHTML | None = None
    cache_layer = "none"
    request_id = getattr(getattr(request, "state", None), "request_id", None)

    # skip_cache skips cache READS only. Writes and usage counting still happen.
    if should_read_persistent_cache(
        database_client,
        persistent_cache_enabled,
        cacheable,
        skip_cache,
        sections,
    ):
        try:
            result = await asyncio.wait_for(
                get_cached_markdown(
                    database_client,
                    url,
                    render_js,
                    include_nav,
                    include_header,
                    include_footer,
                ),
                timeout=DATABASE_TIMEOUT_SECONDS,
            )
        except Exception as error:
            logger.warning(
                "supabase_cache_lookup_failed error_type=%s",
                type(error).__name__,
            )

    cache_key = compute_cache_key(render_js=render_js, links=links, url=url)

    if result is not None:
        cache_layer = "persistent"
        log_cache_event(
            event="cache_hit",
            url=url,
            request_id=request_id,
            layer=cache_layer,
        )

        # Persistent-cache rows contain already-extracted Markdown, not HTML.
        # Return it unchanged: running the HTML extractor again would parse
        # Markdown as HTML and destroy intentional newlines and table shape.
        return document, result, cache_layer

    cache = request.app.state.cache
    document = (
        cache.get(cache_key)
        if should_read_memory_cache(skip_cache, sections)
        else None
    )
    if document is not None:
        cache_layer = "memory"
        log_cache_event(
            event="cache_hit",
            url=url,
            request_id=request_id,
            layer=cache_layer,
        )
    else:
        log_cache_event(
            event="cache_miss",
            url=url,
            request_id=request_id,
            layer="none",
        )

        # robots.txt is checked before any network fetch of the page.
        # skip_cache does not bypass it.
        await _enforce_robots(url, settings, cache_key[:12])

        strategy = resolve_fetch_strategy(render_js)
        if strategy == "rendered":
            document = await fetch_rendered_html_document(url, settings)
        else:
            # The existing transport pins each request to a validated public IP.
            # Keep it off the event loop rather than replacing that SSRF guard
            # with HTTPX's second, independently resolved DNS lookup.
            document = await asyncio.to_thread(
                fetch_html_document,
                url,
                settings,
            )

    extracted = extract_text_result(
        document.body,
        extraction_cap,
        include_nav=include_nav,
        include_header=include_header,
        include_footer=include_footer,
        from_encoding=document.charset,
        base_url=document.final_url or url,
        links=links,
        footnote_url_policy=footnote_url_policy,
        max_footnote_url_length=max_footnote_url_length,
    )

    # Replace raw HTML only after a successful, nonempty extraction.
    if should_write_memory_cache(cache_layer, extracted.text):
        cache.set(cache_key, document)

    result = build_cached_markdown(
        document,
        extracted,
        url,
        decode_source_text_fn=_decode_source_text,
    )

    if should_write_persistent_cache(
        database_client,
        persistent_cache_enabled,
        cacheable,
        persist,
    ):
        try:
            await asyncio.wait_for(
                upsert_cached_markdown(
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
                timeout=DATABASE_TIMEOUT_SECONDS,
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

    return document, result, cache_layer




async def fetch_and_extract(
    request: Request,
    url: str,
    *,
    include_nav: bool,
    include_header: bool,
    include_footer: bool,
    render_js: bool,
    links: Literal["inline", "footnotes", "false"] = "inline",
    skip_cache: bool = False,
    persist: bool = True,
    mode: str = "scrape",
    max_tokens: int = 6000,
    footnote_url_policy: Literal["full", "truncated"] = "truncated",
    max_footnote_url_length: int = 100,
    sections: list[str] | None = None,
) -> tuple[FetchedHTML | None, CachedMarkdown, str]:
    """Public shared fetch -> robots -> cache -> extract boundary."""
    return await _fetch_and_extract(
        request,
        url,
        include_nav=include_nav,
        include_header=include_header,
        include_footer=include_footer,
        render_js=render_js,
        links=links,
        skip_cache=skip_cache,
        persist=persist,
        mode=mode,
        max_tokens=max_tokens,
        footnote_url_policy=footnote_url_policy,
        max_footnote_url_length=max_footnote_url_length,
        sections=sections,
    )














