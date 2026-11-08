from __future__ import annotations
from fastapi import HTTPException
from bintu_api.observability import log_upstream_error
from bintu_api.scraper import (
    PayloadTooLarge,
    RedirectedToPrivateNetwork,
    TargetURLRejected,
    TooManyRedirects,
    UnsupportedContentEncoding,
    UnsupportedMediaType,
    UpstreamHTTPError,
    UpstreamRenderError,
)
"""Shared scraper-exception to HTTP status/code mapping.

This module centralizes the status-code and error-code decision for scraper
exceptions so REST and reader routes stop duplicating that logic. Messages
and hints remain the responsibility of each caller, preserving exact output.
"""


from dataclasses import dataclass


__all__ = ["UpstreamErrorSpec", "resolve_upstream_error"]


@dataclass(frozen=True)
class UpstreamErrorSpec:
    status_code: int
    code: str


def resolve_upstream_error(error: Exception) -> UpstreamErrorSpec | None:
    """Return the canonical (status_code, code) for a scraper exception."""
    if isinstance(error, TargetURLRejected):
        return UpstreamErrorSpec(400, "invalid_or_unsafe_url")
    if isinstance(error, UnsupportedMediaType):
        return UpstreamErrorSpec(415, "unsupported_media_type")
    if isinstance(error, UnsupportedContentEncoding):
        return UpstreamErrorSpec(502, "unsupported_content_encoding")
    if isinstance(error, PayloadTooLarge):
        return UpstreamErrorSpec(413, "payload_too_large")
    if isinstance(error, UpstreamHTTPError):
        if error.status_code == 429:
            return UpstreamErrorSpec(502, "upstream_rate_limited")
        if error.status_code in (401, 402, 403):
            return UpstreamErrorSpec(502, "upstream_access_denied")
        return UpstreamErrorSpec(502, "upstream_http_error")
    if isinstance(error, TooManyRedirects):
        return UpstreamErrorSpec(502, "too_many_redirects")
    if isinstance(error, UpstreamRenderError):
        return UpstreamErrorSpec(502, "upstream_render_error")
    if isinstance(error, TimeoutError):
        return UpstreamErrorSpec(504, "upstream_timeout")
    if isinstance(error, OSError):
        return UpstreamErrorSpec(502, "upstream_connection_error")
    return None


UPSTREAM_ACCESS_DENIED_STATUSES = {401, 402, 403}
UPSTREAM_RATE_LIMITED_STATUSES = {429}


def translate_upstream_error(
    error: Exception, *, url: str, request_id: str
) -> HTTPException:
    """Translate a scraper exception into an HTTPException response."""
    if isinstance(error, RedirectedToPrivateNetwork):
        log_upstream_error(
            error_type="redirect_to_private_network",
            url=url,
            request_id=request_id,
        )
        return HTTPException(
            status_code=400,
            detail={
                "code": "redirect_to_private_network",
                "message": "A redirect attempted to access a private network address.",
                "hint": "Use a public HTTPS URL.",
            },
        )
    if isinstance(error, TargetURLRejected):
        log_upstream_error(
            error_type="invalid_or_unsafe_url",
            url=url,
            request_id=request_id,
        )
        return HTTPException(
            status_code=400,
            detail={
                "code": "invalid_or_unsafe_url",
                "message": str(error),
                "hint": "URL must start with http or https and be publicly accessible.",
            },
        )
    if isinstance(error, UnsupportedMediaType):
        log_upstream_error(
            error_type="unsupported_media_type",
            url=url,
            request_id=request_id,
        )
        return HTTPException(
            status_code=415,
            detail={
                "code": "unsupported_media_type",
                "message": str(error),
                "hint": "Only HTML and XHTML pages are supported.",
            },
        )
    if isinstance(error, UnsupportedContentEncoding):
        log_upstream_error(
            error_type="unsupported_content_encoding",
            url=url,
            request_id=request_id,
        )
        return HTTPException(
            status_code=502,
            detail={
                "code": "unsupported_content_encoding",
                "message": str(error),
                "hint": "The target returned an unsupported or invalid compressed response.",
            },
        )
    if isinstance(error, PayloadTooLarge):
        log_upstream_error(
            error_type="payload_too_large",
            url=url,
            request_id=request_id,
        )
        return HTTPException(
            status_code=413,
            detail={
                "code": "payload_too_large",
                "message": "The page exceeds the 1 MiB size limit.",
                "hint": "The page exceeds the 1 MiB size limit.",
            },
        )
    if isinstance(error, UpstreamHTTPError):
        log_upstream_error(
            error_type="upstream_http_error",
            url=url,
            request_id=request_id,
            status_code=error.status_code,
        )
        if error.status_code == 429:
            return HTTPException(
                status_code=502,
                detail={
                    "code": "upstream_rate_limited",
                    "message": "The target returned HTTP 429.",
                    "hint": "The target is rate limiting requests. Wait before retrying.",
                    "upstream_status": error.status_code,
                },
            )
        if error.status_code in UPSTREAM_ACCESS_DENIED_STATUSES:
            return HTTPException(
                status_code=502,
                detail={
                    "code": "upstream_access_denied",
                    "message": f"The target refused access (HTTP {error.status_code}).",
                    "hint": "Bintu does not retry, log in, solve CAPTCHAs or work around blocks.",
                    "upstream_status": error.status_code,
                },
            )
        return HTTPException(
            status_code=502,
            detail={
                "code": "upstream_http_error",
                "message": f"The target returned HTTP {error.status_code}.",
                "hint": "The target server returned an error. Try again later.",
                "upstream_status": error.status_code,
            },
        )
    if isinstance(error, TooManyRedirects):
        log_upstream_error(
            error_type="too_many_redirects",
            url=url,
            request_id=request_id,
        )
        return HTTPException(
            status_code=502,
            detail={
                "code": "too_many_redirects",
                "message": str(error),
                "hint": "The page has too many redirects.",
            },
        )
    if isinstance(error, UpstreamRenderError):
        log_upstream_error(
            error_type="upstream_render_error",
            url=url,
            request_id=request_id,
        )
        return HTTPException(
            status_code=502,
            detail={
                "code": "upstream_render_error",
                "message": str(error),
                "hint": "The target page could not be rendered.",
            },
        )
    if isinstance(error, TimeoutError):
        log_upstream_error(
            error_type="upstream_timeout",
            url=url,
            request_id=request_id,
        )
        return HTTPException(
            status_code=504,
            detail={
                "code": "upstream_timeout",
                "message": "The target did not respond in time.",
                "hint": "The target server is slow or unresponsive. Try again later.",
            },
        )
    if isinstance(error, OSError):
        log_upstream_error(
            error_type="upstream_connection_error",
            url=url,
            request_id=request_id,
        )
        return HTTPException(
            status_code=502,
            detail={
                "code": "upstream_connection_error",
                "message": "Could not connect to the target.",
                "hint": "The target server may be down or unreachable.",
            },
        )
    log_upstream_error(
        error_type="internal_error",
        url=url,
        request_id=request_id,
    )
    return HTTPException(
        status_code=500,
        detail={
            "code": "internal_error",
            "message": "An internal extraction error occurred.",
        },
    )




