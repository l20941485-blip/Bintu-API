import asyncio
import hashlib
import logging
import socket
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse, urlunparse


from fastapi import APIRouter, HTTPException, Request, Security


from bintu_api.auth import (
    api_key_scheme,
    bearer_scheme,
    has_valid_proxy_secret,
    rate_limit_identity,
    verify_api_access,
    verify_supabase_user,
)
from bintu_api.database import (
    CachedMarkdown,
    DATABASE_TIMEOUT_SECONDS,
    get_cached_markdown,
    increment_developer_usage,
    upsert_cached_markdown,
)
from bintu_api.observability import CACHE_HITS, CACHE_MISSES
from bintu_api.robots import robots_decision, robots_mode
from bintu_api.schemas import (
    CacheInfo,
    ErrorResponse,
    GatewayResponse,
    HealthResponse,
    MobileScrapeTextRequest,
    Provenance,
    ScrapeTextResponse,
    VersionResponse,
)
from bintu_api.scraper import (
    FetchedHTML,
    PayloadTooLarge,
    TargetURLRejected,
    TooManyRedirects,
    UnsupportedContentEncoding,
    UnsupportedMediaType,
    UpstreamHTTPError,
    UpstreamRenderError,
    _compute_approx_tokens,
    _compute_tokens_saved_estimate,
    extract_text_result,
    fetch_html_document,
    fetch_rendered_html_document,
)
from bintu_api.settings import Settings



logger = logging.getLogger("bintu_api.scrape")
router = APIRouter()


TOKEN_METHOD = "ceil(characters/4)"
UPSTREAM_ACCESS_DENIED_STATUSES = (401, 402, 403, 429)



def sanitize_url(url: str) -> str:
    """Strip sensitive-looking query parameters. For logs and provenance only;
    never use the result to fetch or to replace the caller's URL."""
    parsed = urlparse(url)
    safe_query = "&".join(
        part
        for part in parsed.query.split("&")
        if not part.lower().startswith(("key=", "token=", "secret=", "password=", "utm_"))
    )
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, safe_query, parsed.fragment)
    )



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
        fetched_at=datetime.now(timezone.utc).isoformat(),
        requested_url=sanitize_url(url),
        final_url=document.final_url if fetched else None,
        bytes_fetched=len(document.body) if fetched else None,
        content_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
        cache=CacheInfo(hit=cache_layer != "none", layer=cache_layer, age_seconds=None),
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
    saved = (
        _compute_tokens_saved_estimate(document.body, result.markdown)
        if document is not None
        else 0
    )
    return ScrapeTextResponse(
        url=url,
        text=result.markdown,
        truncated=result.truncated,
        cache_layer=cache_layer,
        approx_tokens=approx_tokens,
        token_method=TOKEN_METHOD,
        tokens=approx_tokens,
        tokens_saved_estimate=saved,
        provenance=_build_provenance(url, result.markdown, document, cache_layer, request_id, settings),
    )



async def _enforce_robots(url: str, settings: Settings, url_hash: str) -> None:
    """Check robots.txt before any network fetch of the page.


    enforce: a disallowed (or unretrievable) robots.txt blocks with 403.
    warn:    log and continue.   off: skipped inside robots_decision.
    The blocking check runs in a worker thread. URLs are never logged, only a hash.
    """
    mode = robots_mode(settings)
    if mode == "off":
        return
    decision = await asyncio.to_thread(robots_decision, url, settings)
    if decision.allowed:
        return
    logger.info("robots_not_allowed url_hash=%s mode=%s reason=%s", url_hash, mode, decision.reason)
    if mode == "enforce":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "blocked_by_robots",
                "message": f"Fetching this page is not permitted: {decision.reason}.",
                "hint": "Bintu respects robots.txt. The site owner controls this.",
            },
        )



@router.get("/", response_model=GatewayResponse)
def gateway_check(request: Request) -> GatewayResponse:
    settings = request.app.state.settings
    return GatewayResponse(status="ok", service=settings.service_title, docs="/docs")



@router.get("/healthz", response_model=HealthResponse, include_in_schema=False)
def health_check() -> HealthResponse:
    return HealthResponse(status="ok")



@router.get("/version", response_model=VersionResponse)
def version_info(request: Request) -> VersionResponse:
    """Return service configuration (no secrets)."""
    settings = request.app.state.settings
    return VersionResponse(
        service=settings.service_title,
        version=settings.service_version,
        max_html_bytes=settings.max_html_bytes,
        max_redirects=settings.max_redirects,
        max_text_characters=settings.max_text_characters,
        rate_limit_requests=settings.rate_limit_requests,
        rate_limit_window_seconds=settings.rate_limit_window_seconds,
        cache_ttl_seconds=settings.cache_ttl_seconds,
    )



@router.get(
    "/api/v1/scrape/text",
    response_model=ScrapeTextResponse,
    summary="Extract readable text from a public web page",
    description=(
        "Fetches a public HTML or XHTML page and returns readable text. "
        "The service prefers article or main content, formats headings and tables, "
        "and reports whether the configured text limit truncated the result. "
        "It checks the site's robots.txt first. "
        "JavaScript rendering is disabled unless the service enables it."
    ),
    responses={
        status_code: {"model": ErrorResponse}
        for status_code in (400, 401, 403, 413, 415, 429, 502, 504)
    },
    dependencies=[Security(api_key_scheme, scopes=[])],
)
async def scrape_text(
    request: Request,
    url: str,
    include_nav: bool = False,
    include_header: bool = False,
    include_footer: bool = False,
    render_js: bool = False,
    skip_cache: bool = False,
) -> ScrapeTextResponse:
    settings = request.app.state.settings
    verify_api_access(request, settings)
    if render_js and not settings.render_js_enabled:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "render_js_disabled",
                "message": "JavaScript rendering is disabled on this service.",
                "hint": "Retry with render_js=false for plain HTML extraction.",
            },
        )
    # Delegate to the implementation below (private name kept for test compatibility).
    return await _scrape_text(
        request,
        url,
        include_nav,
        include_header,
        include_footer,
        rate_limit_identity(request, settings),
        render_js,
        skip_cache,
    )



@router.post(
    "/api/v1/mobile/scrape/text",
    response_model=ScrapeTextResponse,
    summary="Extract readable text for a signed-in mobile app user",
    description=(
        "Requires an Authorization Bearer token from the configured Supabase project. "
        "Only users with verified email addresses can use this endpoint."
    ),
    responses={
        status_code: {"model": ErrorResponse}
        for status_code in (400, 401, 403, 413, 415, 429, 502, 503, 504)
    },
    dependencies=[Security(bearer_scheme, scopes=[])],
)
async def mobile_scrape_text(
    request: Request,
    payload: MobileScrapeTextRequest,
    skip_cache: bool = False,
) -> ScrapeTextResponse:
    settings = request.app.state.settings
    user_id = await asyncio.to_thread(
        verify_supabase_user, request, request.app.state.settings
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
        skip_cache,
    )



async def _scrape_text(
    request: Request,
    url: str,
    include_nav: bool,
    include_header: bool,
    include_footer: bool,
    identity: str,
    render_js: bool = False,
    skip_cache: bool = False,
) -> ScrapeTextResponse:
    settings = request.app.state.settings
    request_id = (
        getattr(getattr(request, "state", None), "request_id", None)
        or uuid.uuid4().hex
    )
    try:
        await asyncio.to_thread(request.app.state.rate_limiter.check, identity)


        database_client = getattr(request.app.state, "supabase_client", None)
        result: CachedMarkdown | None = None
        document = None
        cache_layer = "none"


        # skip_cache skips cache READS only. Writes and usage counting still happen.
        if database_client is not None and not skip_cache:
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
                logger.warning("supabase_cache_lookup_failed error_type=%s", type(error).__name__)


        cache_key = hashlib.sha256(f"{int(render_js)}:{url}".encode()).hexdigest()
        if result is not None:
            CACHE_HITS.inc()
            cache_layer = "persistent"
            logger.info("persistent_cache_hit url_hash=%s", cache_key[:12])
            # Persistent-cache row: result.markdown is the extracted text; there is
            # no FetchedHTML body, so rebuild a light result object and mark the
            # layer persistent. No network fetch, no robots.txt check.
            extracted = extract_text_result(
                result.markdown,
                settings.max_text_characters,
                include_nav=include_nav,
                include_header=include_header,
                include_footer=include_footer,
                from_encoding=None,
                base_url=url,
            )
            result = CachedMarkdown(markdown=extracted.text, truncated=extracted.truncated)
        else:
            cache = request.app.state.cache
            document = None if skip_cache else cache.get(cache_key)
            if document is not None:
                CACHE_HITS.inc()
                cache_layer = "memory"
                logger.info("memory_cache_hit url_hash=%s", cache_key[:12])
            else:
                CACHE_MISSES.inc()
                logger.info("cache_miss url_hash=%s", cache_key[:12])
                # robots.txt is checked before any network fetch of the page, and
                # skip_cache does not bypass it.
                await _enforce_robots(url, settings, cache_key[:12])
                if render_js:
                    document = await fetch_rendered_html_document(url, settings)
                else:
                    # The existing transport pins each request to a validated public IP.
                    # Keep it off the event loop rather than replacing that SSRF guard
                    # with HTTPX's second, independently resolved DNS lookup.
                    document = await asyncio.to_thread(fetch_html_document, url, settings)
                cache.set(cache_key, document)


            extracted = extract_text_result(
                document.body,
                settings.max_text_characters,
                include_nav=include_nav,
                include_header=include_header,
                include_footer=include_footer,
                from_encoding=document.charset,
                base_url=document.final_url or url,
            )
            result = CachedMarkdown(markdown=extracted.text, truncated=extracted.truncated)
            if database_client is not None:
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
                        ),
                        timeout=DATABASE_TIMEOUT_SECONDS,
                    )
                except Exception as error:
                    logger.warning("supabase_cache_upsert_failed error_type=%s", type(error).__name__)


        if database_client is not None and has_valid_proxy_secret(request, settings):
            rapidapi_user = request.headers.get("X-RapidAPI-User", "").strip()
            if rapidapi_user and len(rapidapi_user) <= 256 and rapidapi_user.isprintable():
                try:
                    await asyncio.wait_for(
                        increment_developer_usage(database_client, rapidapi_user),
                        timeout=DATABASE_TIMEOUT_SECONDS,
                    )
                except Exception as error:
                    logger.warning("supabase_usage_increment_failed error_type=%s", type(error).__name__)


        return _build_response(
            url,
            result,
            document,
            cache_layer,
            request_id,
            settings,
        )
    except HTTPException:
        raise
    except TargetURLRejected as error:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_or_unsafe_url",
                "message": str(error),
                "hint": "URL must start with http:// or https:// and be publicly accessible",
            },
        ) from error
    except UnsupportedMediaType as error:
        raise HTTPException(
            status_code=415,
            detail={
                "code": "unsupported_media_type",
                "message": str(error),
                "hint": "Only HTML and XHTML pages are supported",
            },
        ) from error
    except UnsupportedContentEncoding as error:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "unsupported_content_encoding",
                "message": str(error),
                "hint": "The target returned an unsupported or invalid compressed response",
            },
        ) from error
    except PayloadTooLarge as error:
        raise HTTPException(
            status_code=413,
            detail={
                "code": "payload_too_large",
                "message": str(error),
                "hint": "The page exceeds the 1 MiB size limit",
            },
        ) from error
    except UpstreamHTTPError as error:
        logger.warning("upstream_http_error status=%d reason=%s", error.status_code, error.reason)
        if error.status_code in UPSTREAM_ACCESS_DENIED_STATUSES:
            # Returned as 502 so a target's 401/403 is never mistaken for a problem
            # with the caller's own API key. No retries, no workarounds.
            raise HTTPException(
                status_code=502,
                detail={
                    "code": "upstream_access_denied",
                    "message": f"The target refused access (HTTP {error.status_code}).",
                    "hint": "Bintu does not retry, log in, solve CAPTCHAs or work around blocks.",
                    "upstream_status": error.status_code,
                },
            ) from error
        raise HTTPException(
            status_code=502,
            detail={
                "code": "upstream_http_error",
                "message": f"The target returned HTTP {error.status_code}.",
                "hint": "The target server returned an error. Try again later.",
            },
        ) from error
    except TooManyRedirects as error:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "too_many_redirects",
                "message": str(error),
                "hint": "The page has too many redirects",
            },
        ) from error
    except UpstreamRenderError as error:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "upstream_render_error",
                "message": str(error),
                "hint": "The target page could not be rendered.",
            },
        ) from error
    except (TimeoutError, socket.timeout) as error:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "upstream_timeout",
                "message": "The target did not respond in time.",
                "hint": "The target server is slow or unresponsive. Try again later.",
            },
        ) from error
    except OSError as error:
        logger.warning("upstream_connection_error error_type=%s", type(error).__name__)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "upstream_connection_error",
                "message": "Could not connect to the target.",
                "hint": "The target server may be down or unreachable.",
            },
        ) from error
    except Exception as error:
        logger.error("scrape_failed error_type=%s", type(error).__name__)
        raise HTTPException(
            status_code=500,
            detail={
                "code": "internal_error",
                "message": "An internal extraction error occurred.",
            },
        ) from error



# Public alias for consumers outside routes.py (context.py, mcp.py).
scrape_text = _scrape_text