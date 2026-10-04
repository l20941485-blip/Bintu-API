import hashlib
import logging
import socket

from fastapi import APIRouter, HTTPException, Request

from bintu_api.auth import rate_limit_identity, verify_api_access, verify_supabase_user
from bintu_api.observability import CACHE_HITS, CACHE_MISSES
from bintu_api.schemas import (
    ErrorResponse,
    GatewayResponse,
    HealthResponse,
    MobileScrapeTextRequest,
    ScrapeTextResponse,
    VersionResponse,
)
from bintu_api.scraper import (
    PayloadTooLarge,
    TargetURLRejected,
    TooManyRedirects,
    UnsupportedContentEncoding,
    UnsupportedMediaType,
    UpstreamHTTPError,
    extract_text_result,
    fetch_html_document,
)


logger = logging.getLogger("bintu_api.scrape")
router = APIRouter()


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
        "It does not execute JavaScript or bypass access controls."
    ),
    responses={
        status_code: {"model": ErrorResponse}
        for status_code in (400, 401, 413, 415, 429, 502, 504)
    },
)
def scrape_text(
    request: Request,
    url: str,
    include_nav: bool = False,
    include_header: bool = False,
    include_footer: bool = False,
) -> ScrapeTextResponse:
    settings = request.app.state.settings
    verify_api_access(request, settings)
    return _scrape_text(
        request,
        url,
        include_nav,
        include_header,
        include_footer,
        rate_limit_identity(request, settings),
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
)
def mobile_scrape_text(request: Request, payload: MobileScrapeTextRequest) -> ScrapeTextResponse:
    user_id = verify_supabase_user(request, request.app.state.settings)
    return _scrape_text(
        request,
        payload.url,
        payload.include_nav,
        payload.include_header,
        payload.include_footer,
        f"supabase:{user_id}",
    )


def _scrape_text(
    request: Request,
    url: str,
    include_nav: bool,
    include_header: bool,
    include_footer: bool,
    identity: str,
) -> ScrapeTextResponse:
    settings = request.app.state.settings
    try:
        request.app.state.rate_limiter.check(identity)

        # Check cache first
        cache_key = hashlib.sha256(url.encode()).hexdigest()
        cache = request.app.state.cache
        cached = cache.get(cache_key)
        if cached is not None:
            CACHE_HITS.inc()
            logger.info("cache_hit url_hash=%s", cache_key[:12])
            document = cached
        else:
            CACHE_MISSES.inc()
            logger.info("cache_miss url_hash=%s", cache_key[:12])
            document = fetch_html_document(url, settings)
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
        return ScrapeTextResponse(
            url=url,
            text=extracted.text,
            truncated=extracted.truncated,
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
