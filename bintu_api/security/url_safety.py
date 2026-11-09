"""URL sanitization for logs and response provenance.

This module owns privacy-safe URL shaping. It never performs network access
and never replaces the caller's original URL for fetching.
"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

SENSITIVE_QUERY_PARAMETER_NAMES = frozenset(
    {
        "key",
        "token",
        "secret",
        "password",
        "api_key",
        "apikey",
        "access_token",
        "refresh_token",
        "client_secret",
    }
)


def sanitize_url(url: str) -> str:
    """Strip sensitive-looking query parameters.

    For logs and provenance only; never use the result to fetch or to replace
    the caller's URL. Parameter names are compared case-insensitively, and
    tracking parameters such as ``utm_source`` are removed as well.
    """
    parsed = urlparse(url)
    safe_query = "&".join(
        part
        for part in parsed.query.split("&")
        if part and not _is_sensitive_query_parameter(part.split("=", 1)[0])
    )
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            safe_query,
            parsed.fragment,
        )
    )


def _is_sensitive_query_parameter(name: str) -> bool:
    normalized = name.strip().lower()
    return (
        normalized in SENSITIVE_QUERY_PARAMETER_NAMES
        or normalized.startswith("utm_")
    )
