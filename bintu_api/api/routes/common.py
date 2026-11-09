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
import hashlib
import logging
from datetime import UTC, datetime
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException, Request

from bintu_api.context import (
    DEFAULT_MAX_TEXT_CHARACTERS,
    MAX_EXTRACTION_CHARACTERS,
    _decode_source_text,
)
from bintu_api.database import (
    DATABASE_TIMEOUT_SECONDS,
    CachedMarkdown,
    get_cached_markdown,
    upsert_cached_markdown,
)
from bintu_api.extraction.cache import compute_saved_tokens
from bintu_api.extraction.quality import assess_yield
from bintu_api.observability import log_cache_event
from bintu_api.robots import robots_decision, robots_mode
from bintu_api.schemas import CacheInfo, Provenance, ScrapeTextResponse
from bintu_api.scraper import (
    FetchedHTML,
    _compute_approx_tokens,
    _compute_tokens_saved_estimate,
    extract_text_result,
    fetch_html_document,
    fetch_rendered_html_document,
)
from bintu_api.security.credentials import (
    CREDENTIAL_QUERY_PARAMS,
    has_credential_params,
)
from bintu_api.security.url_safety import (
    SENSITIVE_QUERY_PARAMETER_NAMES,
    sanitize_url,
)
from bintu_api.settings import Settings

logger = logging.getLogger("bintu_api.scrape")

TOKEN_METHOD = "ceil(characters/4)"
LINK_MODES = ("inline", "footnotes", "false")


def _is_sensitive_query_parameter(name: str) -> bool:
    normalized = name.strip().lower()
    return normalized in SENSITIVE_QUERY_PARAMETER_NAMES or normalized.startswith("utm_")


def _build_provenance(
    url: str,
    text: str,
    document: FetchedHTML | None,
    cache_layer: str,
    request_id: str,
    settings: Settings,
) -> Provenance:
    """Provenance with real values only; fields that do not apply stay None."""
    fetched = document is not None and cache_layer == "none"
    return Provenance(
        request_id=request_id,
        fetched_at=datetime.now(UTC).isoformat(),
        requested_url=sanitize_url(url),
        final_url=document.final_url if fetched else None,
        bytes_fetched=len(document.body) if fetched else None,
        content_sha256=(hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None),
        cache=CacheInfo(
            hit=cache_layer != "none",
            layer=cache_layer,
            age_seconds=None,
        ),
        extractor_version=getattr(settings, "service_version", "unknown"),
    )


def _build_response(
    url: str,
    result: CachedMarkdown,
    document: FetchedHTML | None,
    cache_layer: str,
    request_id: str,
    settings: Settings,
) -> ScrapeTextResponse:
    approx_tokens = _compute_approx_tokens(result.markdown)

    # Preserve the economics of the original extraction on cache hits. A
    # persistent-cache row no longer has the source HTML, so recomputing savings
    # would incorrectly report zero.
    saved = compute_saved_tokens(document, result, cache_layer)

    assessment = assess_yield(approx_tokens, result.html_tokens)

    return ScrapeTextResponse(
        url=url,
        text=result.markdown,
        truncated=result.truncated,
        cache_hit=cache_layer != "none",
        cache_layer=cache_layer,
        approx_tokens=approx_tokens,
        token_method=TOKEN_METHOD,
        tokens=approx_tokens,
        tokens_saved_estimate=saved,
        low_yield=assessment.low_yield,
        yield_hint=assessment.hint,
        provenance=_build_provenance(
            url,
            result.markdown,
            document,
            cache_layer,
            request_id,
            settings,
        ),
    )


async def _enforce_robots(url: str, settings: Settings, url_hash: str) -> None:
    """Check robots.txt before any network fetch of the page.


    enforce: an explicit robots disallow blocks with 403. A robots.txt retrieval
    failure also blocks with 403, but is reported as ``robots_unreachable``.
    warn: log and continue. off: skipped inside robots_decision.
    The blocking check runs in a worker thread. URLs are never logged, only a hash.
    """
    mode = robots_mode(settings)
    if mode == "off":
        return

    decision = await asyncio.to_thread(robots_decision, url, settings)
    if decision.allowed:
        return

    logger.info(
        "robots_not_allowed url_hash=%s mode=%s unreachable=%s reason=%s",
        url_hash,
        mode,
        decision.unreachable,
        decision.reason,
    )

    if mode == "enforce":
        if decision.unreachable:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "robots_unreachable",
                    "message": (f"Fetching this page is not permitted: {decision.reason.rstrip('.')}."),
                    "hint": (
                        "The target's robots.txt could not be retrieved. "
                        "Access is denied while robots enforcement is enabled."
                    ),
                },
            )

        raise HTTPException(
            status_code=403,
            detail={
                "code": "blocked_by_robots",
                "message": (f"Fetching this page is not permitted: {decision.reason.rstrip('.')}."),
                "hint": ("Bintu respects robots.txt. The site owner controls this."),
            },
        )


def redact_cache_url(url: str) -> str:
    """Redact credential-like query values before persistent-cache storage.


    Cache lookups continue to use the original request URL. Only the URL
    written to Supabase is redacted, preventing bearer tokens, session IDs,
    and similar caller credentials from being retained in cache rows.
    """
    parsed = urlsplit(url)
    if not parsed.query:
        return url

    try:
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
    except ValueError:
        return url

    redacted_pairs = [
        (name, "[REDACTED]" if name.lower() in CREDENTIAL_QUERY_PARAMS else value) for name, value in pairs
    ]

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(redacted_pairs),
            parsed.fragment,
        )
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
    """Shared fetch -> robots -> cache -> extract boundary for REST and MCP.


    Returns:
        document: FetchedHTML for a fresh fetch; None for a cache hit.
        result: extracted markdown, truncation flag, and extraction economics.
        cache_layer: "none", "memory", or "persistent".


    Raises the same HTTPException and scraper exceptions as the REST endpoint.
    """
    if links not in LINK_MODES:
        raise ValueError("links must be one of: inline, footnotes, false")

    settings = request.app.state.settings
    extraction_cap = (
        MAX_EXTRACTION_CHARACTERS
        if settings.max_text_characters == DEFAULT_MAX_TEXT_CHARACTERS
        else min(settings.max_text_characters, MAX_EXTRACTION_CHARACTERS)
    )
    # Persistent rows share one canonical extraction policy.
    # Custom operator caps use raw-HTML memory caching only.
    persistent_cache_enabled = settings.max_text_characters == DEFAULT_MAX_TEXT_CHARACTERS
    # Link output changes the extracted Markdown, so only the default inline
    # mode may use the existing persistent-cache policy until its schema is
    # extended to store the link mode.
    persistent_cache_enabled = persistent_cache_enabled and links == "inline"
    # Never persist URLs whose query string may carry a caller credential.
    cacheable = not has_credential_params(url)
    database_client = getattr(request.app.state, "supabase_client", None)
    result: CachedMarkdown | None = None
    document: FetchedHTML | None = None
    cache_layer = "none"
    request_id = getattr(getattr(request, "state", None), "request_id", None)

    # skip_cache skips cache READS only. Writes and usage counting still happen.
    if (
        database_client is not None
        and persistent_cache_enabled
        and cacheable
        and not skip_cache
        and sections is None
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

    cache_key = hashlib.sha256(f"{int(render_js)}:{links}:{url}".encode()).hexdigest()

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
    document = None if skip_cache or sections is not None else cache.get(cache_key)
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

        if render_js:
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
    if cache_layer == "none" and extracted.text.strip():
        cache.set(cache_key, document)

    html_source_text = _decode_source_text(document)
    html_tokens = _compute_approx_tokens(html_source_text)
    tokens_saved_estimate = _compute_tokens_saved_estimate(
        document.body,
        extracted.text,
    )
    extracted_at = datetime.now(UTC).isoformat()

    result = CachedMarkdown(
        markdown=extracted.text,
        truncated=extracted.truncated,
        html_tokens=html_tokens,
        tokens_saved_estimate=tokens_saved_estimate,
        limiting_factor="char_cap" if extracted.truncated else "none",
        extracted_at=extracted_at,
    )

    if database_client is not None and persistent_cache_enabled and cacheable and persist:
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

