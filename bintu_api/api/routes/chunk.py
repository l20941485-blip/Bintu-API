"""Chunked extraction endpoint for the Bintu API.

This module owns the POST /api/v1/scrape/chunks route and its helper, which
fetch a page, extract readable text, and split it into token-budgeted chunks.

Important boundaries, invariants, or compatibility notes:
- Delegates the fetch -> robots -> cache -> extract boundary to common.py.
- Response shape and chunking behavior must remain identical to routes.py.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Security

from bintu_api.api.schemas import (
    ErrorResponse,
    MobileScrapeTextRequest,
    RestChunk,
    ScrapeChunksResponse,
)
from bintu_api.errors.upstream import translate_upstream_error
from bintu_api.extraction import service as routes_common
from bintu_api.extraction.cache_store import CachedMarkdown
from bintu_api.extraction.context import split_into_chunks
from bintu_api.extraction.output import TOKEN_METHOD
from bintu_api.observability import log_extraction_completed
from bintu_api.scraper.fetcher import FetchedHTML, _compute_approx_tokens
from bintu_api.security.auth import api_key_scheme

router = APIRouter(tags=["Extraction"])


@router.post(
    "/api/v1/scrape/chunks",
    response_model=ScrapeChunksResponse,
    summary="Extract readable text as approximately token-budgeted chunks",
    description=(
        "Fetches a public HTML or XHTML page, extracts readable text, and "
        "returns fence-aware chunks sized to the requested token budget. "
        "The extraction character ceiling applies before chunking."
    ),
    responses={status_code: {"model": ErrorResponse} for status_code in (400, 401, 403, 413, 415, 429, 502, 504)},
    dependencies=[Security(api_key_scheme, scopes=[])],
)
async def scrape_chunks(
    request: Request,
    payload: MobileScrapeTextRequest,
    max_tokens: int = 6000,
    links: Literal["inline", "footnotes", "false"] = "inline",
    skip_cache: bool = False,
    persist: bool = True,
) -> ScrapeChunksResponse:
    settings = request.app.state.settings
    routes_common.verify_api_access(request, settings)

    if not 100 <= max_tokens <= 50000:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_token_budget",
                "message": "max_tokens must be between 100 and 50000.",
            },
        )

    if payload.render_js and not settings.render_js_enabled:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "render_js_disabled",
                "message": "JavaScript rendering is disabled on this service.",
                "hint": "Retry with render_js=false for plain HTML extraction.",
            },
        )

    document, result, cache_layer = await _scrape_chunks(
        request,
        payload.url,
        payload.include_nav,
        payload.include_header,
        payload.include_footer,
        routes_common.rate_limit_identity(request, settings),
        payload.render_js,
        links,
        skip_cache,
        persist,
        max_tokens,
    )

    chunk_strings = split_into_chunks(result.markdown, max_tokens)
    chunks = [
        RestChunk(
            index=index,
            text=chunk,
            approx_tokens=_compute_approx_tokens(chunk),
            tokens=_compute_approx_tokens(chunk),
        )
        for index, chunk in enumerate(chunk_strings)
    ]

    approx_tokens = sum(chunk.approx_tokens for chunk in chunks)

    return ScrapeChunksResponse(
        url=payload.url,
        mode="chunk",
        max_tokens=max_tokens,
        tokens=approx_tokens,
        approx_tokens=approx_tokens,
        html_tokens=result.html_tokens,
        token_method=TOKEN_METHOD,
        limiting_factor="token_budget" if result.truncated else "none",
        chunk_count=len(chunks),
        cache_hit=cache_layer != "none",
        cache_layer=cache_layer,
        source_url=document.final_url if document else payload.url,
        extracted_at=result.extracted_at,
        tokens_saved_estimate=max(
            0,
            result.html_tokens - approx_tokens,
        ),
        truncated=result.truncated,
        split=len(chunks) > 1,
        chunks=chunks,
    )


async def _scrape_chunks(
    request: Request,
    url: str,
    include_nav: bool,
    include_header: bool,
    include_footer: bool,
    identity: str,
    render_js: bool = False,
    links: Literal["inline", "footnotes", "false"] = "inline",
    skip_cache: bool = False,
    persist: bool = True,
    max_tokens: int = 6000,
) -> tuple[FetchedHTML | None, CachedMarkdown, str]:
    settings = request.app.state.settings
    request_id = getattr(getattr(request, "state", None), "request_id", None) or uuid.uuid4().hex

    try:
        await asyncio.to_thread(
            request.app.state.rate_limiter.check,
            identity,
        )

        document, result, cache_layer = await routes_common.fetch_and_extract(
            request,
            url,
            include_nav=include_nav,
            include_header=include_header,
            include_footer=include_footer,
            render_js=render_js,
            links=links,
            skip_cache=skip_cache,
            persist=persist,
            mode="chunk",
            max_tokens=max_tokens,
        )

        log_extraction_completed(
            request_id=request_id,
            url=url,
            mode="chunk",
            cache_hit=cache_layer != "none",
            cache_layer=cache_layer,
            approx_tokens=_compute_approx_tokens(result.markdown),
            html_tokens=result.html_tokens,
            tokens_saved_estimate=result.tokens_saved_estimate,
            truncated=result.truncated,
            limiting_factor=result.limiting_factor,
        )

        return document, result, cache_layer

    except HTTPException:
        raise
    except Exception as error:
        raise translate_upstream_error(
            error,
            url=url,
            request_id=request_id,
        ) from error



