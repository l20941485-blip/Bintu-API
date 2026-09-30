import logging
import socket

from fastapi import APIRouter, HTTPException, Request

from bintu_api.auth import rate_limit_identity, verify_api_access
from bintu_api.schemas import ErrorResponse, GatewayResponse, HealthResponse, ScrapeTextResponse
from bintu_api.scraper import (
    PayloadTooLarge,
    TargetURLRejected,
    TooManyRedirects,
    UnsupportedMediaType,
    UpstreamHTTPError,
    extract_text,
    fetch_html,
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


@router.get(
    "/api/v1/scrape/text",
    response_model=ScrapeTextResponse,
    responses={
        status_code: {"model": ErrorResponse}
        for status_code in (400, 401, 413, 415, 429, 502, 504)
    },
)
def scrape_text(request: Request, url: str) -> ScrapeTextResponse:
    settings = request.app.state.settings
    try:
        verify_api_access(request, settings)
        request.app.state.rate_limiter.check(rate_limit_identity(request, settings))
        html_bytes = fetch_html(url, settings)
        text = extract_text(html_bytes, settings.max_text_characters)
        return ScrapeTextResponse(url=url, text=text)
    except HTTPException:
        raise
    except TargetURLRejected as error:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_or_unsafe_url", "message": str(error)},
        ) from error
    except UnsupportedMediaType as error:
        raise HTTPException(
            status_code=415,
            detail={"code": "unsupported_media_type", "message": str(error)},
        ) from error
    except PayloadTooLarge as error:
        raise HTTPException(
            status_code=413,
            detail={"code": "payload_too_large", "message": str(error)},
        ) from error
    except UpstreamHTTPError as error:
        logger.warning("upstream_http_error status=%d reason=%s", error.status_code, error.reason)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "upstream_http_error",
                "message": f"The target returned HTTP {error.status_code}.",
            },
        ) from error
    except TooManyRedirects as error:
        raise HTTPException(
            status_code=502,
            detail={"code": "too_many_redirects", "message": str(error)},
        ) from error
    except (TimeoutError, socket.timeout) as error:
        raise HTTPException(
            status_code=504,
            detail={"code": "upstream_timeout", "message": "The target did not respond in time."},
        ) from error
    except OSError as error:
        logger.warning("upstream_connection_error error_type=%s", type(error).__name__)
        raise HTTPException(
            status_code=502,
            detail={"code": "upstream_connection_error", "message": "Could not connect to the target."},
        ) from error
    except Exception as error:
        logger.error("scrape_failed error_type=%s", type(error).__name__)
        raise HTTPException(
            status_code=500,
            detail={"code": "internal_error", "message": "An internal extraction error occurred."},
        ) from error