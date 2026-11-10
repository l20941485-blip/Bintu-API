"""Scrape-text extraction endpoints for the Bintu API.

This module owns the REST scrape-text route, the mobile authenticated route,
and the shared scrape helper that applies sections selection and token
budgeting on top of the shared fetch/extract boundary.

Important boundaries, invariants, or compatibility notes:
- Delegates the fetch -> robots -> cache -> extract boundary to common.py.
- Response shape, sections selection, and token budgeting must remain
  identical to routes.py.
- Does not perform MCP JSON-RPC formatting or Supabase persistence directly.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Request, Security

from bintu_api.api.routes.common import (
    _build_response,
)
from bintu_api.api.schemas import (
    ErrorResponse,
    MobileScrapeTextRequest,
    ScrapeTextResponse,
)
from bintu_api.errors.upstream import translate_upstream_error
from bintu_api.extraction import service as routes_common
from bintu_api.extraction.sections import select_sections
from bintu_api.extraction.token_budget import truncate_to_token_budget
from bintu_api.metering.service import UsageEvent, queue_usage_event
from bintu_api.observability import log_extraction_completed
from bintu_api.scraper.fetcher import _compute_approx_tokens
from bintu_api.security.auth import (
    api_key_scheme,
    bearer_scheme,
    verify_supabase_user,
)

router = APIRouter(tags=["Extraction"])


@router.get(
    "/api/v1/scrape/text",
    response_model=ScrapeTextResponse,
    summary="Extract readable text from a public web page",
    description=(
        "Fetches a public HTML or XHTML page and returns readable text. "
        "The service prefers article or main content, formats headings andtables, "
        "and reports whether the configured text limit truncated the result. "
        "The service checks the site's robots.txt first. "
        "JavaScript rendering is disabled unless the service enables it."
    ),
    responses={status_code: {"model": ErrorResponse} for status_code in (400, 401, 403, 413, 415, 429, 502, 504)},
    dependencies=[Security(api_key_scheme, scopes=[])],
)
async def scrape_text(
    request: Request,
    url: str,
    include_nav: bool = False,
    include_header: bool = False,
    include_footer: bool = False,
    render_js: bool = False,
    links: Literal["inline", "footnotes", "false"] = "inline",
    footnote_url_policy: Literal["full", "truncated"] = "truncated",
    max_footnote_url_length: int = Query(default=100, gt=0),
    skip_cache: bool = False,
    persist: bool = True,
    max_tokens: int = 6000,
    sections: Annotated[list[str] | None, Query()] = None,
) -> ScrapeTextResponse:
    settings = request.app.state.settings
    routes_common.verify_api_access(request, settings)

    if max_tokens < 100 or max_tokens > 50000:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_max_tokens",
                "message": "max_tokens must be between 100 and 50000.",
            },
        )
    if sections is not None:
        if any(not isinstance(item, str) for item in sections):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_arguments",
                    "message": "sections must be an array of strings.",
                },
            )

        if any(not item.strip() for item in sections):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_arguments",
                    "message": "sections cannot contain empty or whitespace-only values.",
                },
            )

        if any(len(item) > 200 for item in sections):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "invalid_arguments",
                    "message": "Each section selector must be 200 characters or fewer.",
                },
            )

    if render_js and not settings.render_js_enabled:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "render_js_disabled",
                "message": "JavaScript rendering is disabled on this service.",
                "hint": "Retry with render_js=false for plain HTML extraction.",
            },
        )

    return await _scrape_text(
        request,
        url,
        include_nav,
        include_header,
        include_footer,
        routes_common.rate_limit_identity(request, settings),
        render_js,
        links,
        skip_cache,
        persist,
        max_tokens,
        footnote_url_policy=footnote_url_policy,
        max_footnote_url_length=max_footnote_url_length,
        sections=sections,
    )


@router.post(
    "/api/v1/mobile/scrape/text",
    response_model=ScrapeTextResponse,
    summary="Extract readable text for a signed-in mobile app user",
    description=(
        "Requires an Authorization Bearer token from the configured Supabase project. "
        "Only users with verified email addresses can use this endpoint."
    ),
    responses={status_code: {"model": ErrorResponse} for status_code in (400, 401, 403, 413, 415, 429, 502, 503, 504)},
    dependencies=[Security(bearer_scheme, scopes=[])],
)
async def mobile_scrape_text(
    request: Request,
    payload: MobileScrapeTextRequest,
    links: Literal["inline", "footnotes", "false"] = "inline",
    skip_cache: bool = False,
    persist: bool = True,
) -> ScrapeTextResponse:
    settings = request.app.state.settings
    user_id = await asyncio.to_thread(
        verify_supabase_user,
        request,
        request.app.state.settings,
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

    return await _scrape_text(
        request,
        payload.url,
        payload.include_nav,
        payload.include_header,
        payload.include_footer,
        f"supabase:{user_id}",
        payload.render_js,
        links,
        skip_cache,
        persist,
    )


async def _scrape_text(
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
    footnote_url_policy: Literal["full", "truncated"] = "truncated",
    max_footnote_url_length: int = 100,
    sections: list[str] | None = None,
) -> ScrapeTextResponse:
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
            max_tokens=max_tokens,
            footnote_url_policy=footnote_url_policy,
            max_footnote_url_length=max_footnote_url_length,
            sections=sections,
        )

        if request.app.state.supabase_client is not None and routes_common.has_valid_proxy_secret(request, settings):
            rapidapi_user = request.headers.get("X-RapidAPI-User", "").strip()
            if rapidapi_user and len(rapidapi_user) <= 256 and rapidapi_user.isprintable():
                queue_usage_event(
                    request,
                    UsageEvent(
                        identity=rapidapi_user,
                        legacy_rpc=True,
                        source="rest",
                    ),
                )

        response = _build_response(
            url,
            result,
            document,
            cache_layer,
            request_id,
            settings,
        )

        if sections is not None:
            selection = select_sections(
                response.text,
                sections,
                max_tokens,
            )

            response.selected_sections = selection.sections
            response.text = selection.text
            response.truncated = selection.truncated
            response.limiting_factor = (
                "token_budget" if selection.truncated else "none"
            )

            if not selection.sections:
                response.low_yield = False
                response.yield_hint = None
            
            response.approx_tokens = _compute_approx_tokens(selection.text)
            response.tokens = response.approx_tokens
            response.tokens_saved_estimate = max(
                0,
                result.html_tokens - response.approx_tokens,
            )
        else:
            text, token_truncated = truncate_to_token_budget(
                response.text,
                max_tokens,
            )

            if token_truncated:
                response.text = text
                response.truncated = True
                response.limiting_factor = "token_budget"
                response.approx_tokens = max(0, -(-len(text) // 4))
                response.tokens = response.approx_tokens
                response.tokens_saved_estimate = max(
                    0,
                    result.html_tokens - response.approx_tokens,
                )
        log_extraction_completed(
            request_id=request_id,
            url=url,
            mode="scrape",
            cache_hit=cache_layer != "none",
            cache_layer=cache_layer,
            approx_tokens=response.approx_tokens,
            html_tokens=result.html_tokens,
            tokens_saved_estimate=response.tokens_saved_estimate,
            truncated=response.truncated,
            limiting_factor=result.limiting_factor,
        )

        return response

    except HTTPException:
        raise
    except Exception as error:
        raise translate_upstream_error(
            error,
            url=url,
            request_id=request_id,
        ) from error

