"""Chunked extraction endpoint for the Bintu API.

This module owns the POST /api/v1/scrape/chunks route and its helper, which
fetch a page, extract readable text, and split it into token-budgeted chunks.

Important boundaries, invariants, or compatibility notes:
- Delegates the fetch -> robots -> cache -> extract boundary to common.py.
- Response shape and chunking behavior must remain identical to routes.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Security

from bintu_api.api import scrape_adapter as routes_common
from bintu_api.api.schemas import (
    ErrorResponse,
    MobileScrapeTextRequest,
    RestChunk,
    ScrapeChunksResponse,
)
from bintu_api.errors.upstream import translate_upstream_error
from bintu_api.extraction.cache_store import CachedMarkdown
from bintu_api.extraction.context import split_into_chunks
from bintu_api.extraction.output import TOKEN_METHOD, sanitize_url
from bintu_api.extraction.rag_chunking import split_semantic_chunks
from bintu_api.observability import get_or_create_trace_id, log_extraction_completed, record_stage_trace
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
    chunk_strategy: Literal["sequential", "semantic"] = "sequential",
    overlap_tokens: int = 0,
    return_metadata: bool = True,
    include_heading_path: bool = True,
    include_page_context: bool = True,
) -> ScrapeChunksResponse:
    settings = request.app.state.settings
    request_id = getattr(getattr(request, "state", None), "request_id", None) or uuid.uuid4().hex
    trace_id = get_or_create_trace_id(request_id)
    routes_common.verify_api_access(request, settings)

    if not 100 <= max_tokens <= 50000:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_token_budget",
                "message": "max_tokens must be between 100 and 50000.",
            },
        )

    if overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_overlap_budget",
                "message": "overlap_tokens must be non-negative and less than max_tokens.",
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

    document, result, cache_layer, revalidated = await _scrape_chunks(
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
        payload.main_content_only,
        exclude_terminal_sections=payload.exclude_terminal_sections,
    )

    chunking_started: float | None = None
    chunking_tokens: int | None = None
    if chunk_strategy == "semantic":
        chunking_started = time.perf_counter()
        try:
            semantic_chunks = split_semantic_chunks(
                result.markdown,
                max_tokens=max_tokens,
                overlap_tokens=overlap_tokens,
                source_url=sanitize_url(payload.url),
                final_url=document.final_url if document else payload.url,
                content_sha256=result.content_hash,
                extracted_at=result.extracted_at,
            )
            chunks = [
                RestChunk(
                    index=chunk.index,
                    text=chunk.text,
                    approx_tokens=chunk.approx_tokens,
                    tokens=chunk.tokens,
                    chunk_strategy=chunk.chunk_strategy,
                    chunk_id=chunk.chunk_id,
                    heading_path=chunk.heading_path if include_heading_path else None,
                    section_index=chunk.section_index,
                    contains_code=chunk.contains_code if return_metadata else None,
                    contains_table=chunk.contains_table if return_metadata else None,
                    contains_links=chunk.contains_links if return_metadata else None,
                    link_count=chunk.link_count if return_metadata else None,
                    source_url=chunk.source_url if return_metadata else None,
                    final_url=chunk.final_url if return_metadata else None,
                    content_sha256=result.content_hash if return_metadata else None,
                    extracted_at=chunk.extracted_at if return_metadata else None,
                    page_title=result.page_title if return_metadata else None,
                    content_fingerprint=result.content_fingerprint if return_metadata else None,
                    chunk_sha256=(hashlib.sha256(chunk.text.encode("utf-8")).hexdigest() if return_metadata else None),
                    page_context=(
                        (
                            " | ".join(
                                part
                                for part in (
                                    (f"Page: {result.page_title}" if result.page_title else None),
                                    ("Section: " + " > ".join(chunk.heading_path) if chunk.heading_path else None),
                                )
                                if part
                            )
                            or "No additional page context available."
                        )
                        if include_page_context
                        else None
                    ),
                )
                for chunk in semantic_chunks
            ]
            chunking_tokens = sum(chunk.approx_tokens for chunk in chunks)
        except Exception:
            record_stage_trace(
                request_id=request_id,
                trace_id=trace_id,
                stage="chunking",
                status="error",
                duration_ms=(time.perf_counter() - chunking_started) * 1000.0,
                cache_layer=cache_layer,
            )
            raise
    else:
        chunk_strings = split_into_chunks(result.markdown, max_tokens)
        chunks = [
            RestChunk(
                index=index,
                text=chunk,
                approx_tokens=_compute_approx_tokens(chunk),
                tokens=_compute_approx_tokens(chunk),
                chunk_strategy="sequential",
                heading_path=None if not include_heading_path else [],
                page_context=(
                    (f"Page: {result.page_title}" if result.page_title else "No additional page context available.")
                    if include_page_context
                    else None
                ),
            )
            for index, chunk in enumerate(chunk_strings)
        ]

    approx_tokens = sum(chunk.approx_tokens for chunk in chunks)
    if chunking_started is not None:
        record_stage_trace(
            request_id=request_id,
            trace_id=trace_id,
            stage="chunking",
            status="success",
            duration_ms=(time.perf_counter() - chunking_started) * 1000.0,
            cache_layer=cache_layer,
            tokens_returned=chunking_tokens if chunking_tokens is not None else approx_tokens,
        )

    delivery_started = time.perf_counter()
    record_stage_trace(
        request_id=request_id,
        trace_id=trace_id,
        stage="response_delivery",
        status="success",
        duration_ms=(time.perf_counter() - delivery_started) * 1000.0,
        cache_layer=cache_layer,
        tokens_returned=approx_tokens,
    )

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
        revalidated=revalidated,
        source_url=sanitize_url(payload.url),
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
    main_content_only: bool = False,
    exclude_terminal_sections: bool = False,
) -> tuple[FetchedHTML | None, CachedMarkdown, str, bool]:
    settings = request.app.state.settings
    request_id = getattr(getattr(request, "state", None), "request_id", None) or uuid.uuid4().hex

    try:
        await asyncio.to_thread(
            request.app.state.rate_limiter.check,
            identity,
        )

        document, result, cache_layer, revalidated = await routes_common.fetch_and_extract(
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
            main_content_only=main_content_only,
            exclude_terminal_sections=exclude_terminal_sections,
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

        return document, result, cache_layer, revalidated

    except HTTPException:
        raise
    except Exception as error:
        raise translate_upstream_error(
            error,
            url=url,
            request_id=request_id,
        ) from error
