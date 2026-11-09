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

import logging
from typing import Literal

from fastapi import Request

from bintu_api.auth import has_valid_proxy_secret as has_valid_proxy_secret
from bintu_api.auth import rate_limit_identity as rate_limit_identity
from bintu_api.auth import verify_api_access as verify_api_access
from bintu_api.database import (
    CachedMarkdown,
    get_cached_markdown,
    upsert_cached_markdown,
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
from bintu_api.extraction.request_context import ScrapeRequestContext
from bintu_api.extraction.scrape_service import ScrapeService
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

def build_scrape_service(request: Request) -> ScrapeService:
    """Build a scrape service using the request-scoped collaborators."""
    return ScrapeService(
        cache=request.app.state.cache,
        persistent_cache_reader=get_cached_markdown,
        persistent_cache_writer=upsert_cached_markdown,
        robots_enforcer=_enforce_robots,
        html_fetcher=fetch_html_document,
        rendered_html_fetcher=fetch_rendered_html_document,
        text_extractor=extract_text_result,
        source_decoder=_decode_source_text,
        cache_event_logger=log_cache_event,
    )


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
    """Compatibility boundary preserving the established scrape patch seams."""
    context = ScrapeRequestContext(
        settings=request.app.state.settings,
        database_client=getattr(request.app.state, "supabase_client", None),
        request_id=getattr(getattr(request, "state", None), "request_id", None),
    )
    service = build_scrape_service(request)
    return await service.fetch_and_extract(
        context,
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
























