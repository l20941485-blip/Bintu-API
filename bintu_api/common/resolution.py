"""Pure URL-resolution classification and normalization contracts.

This module intentionally performs no network I/O. Fetching, redirect
validation, SSRF protection, and canonical-URL extraction remain owned by
their existing modules.
"""

from __future__ import annotations

from urllib.parse import urlsplit


def classify_content_type(content_type: str | None) -> str:
    """Classify an upstream Content-Type header into a coarse media class.

    The input may be a full header value, including parameters such as
    ``text/html; charset=utf-8``. The returned value is a stable internal
    classification, not the original header.
    """
    if not content_type:
        return "unsupported"

    media_type = content_type.split(";", 1)[0].strip().lower()

    if media_type in {"text/html", "application/xhtml+xml"}:
        return "html"

    if media_type == "application/pdf":
        return "pdf"

    if media_type in {"application/json", "text/json"}:
        return "json"

    if media_type == "text/plain":
        return "text"

    if media_type.startswith("image/"):
        return "image"

    return "unsupported"


def normalize_url(url: str) -> str:
    """Return a normalized absolute HTTP or HTTPS URL.

    This is a lightweight normalization helper for stable display and
    provenance. It does not replace the fetcher's security validation.
    """
    parsed = urlsplit(url.strip())

    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()

    if scheme not in {"http", "https"} or not host:
        raise ValueError("URL must be an absolute HTTP or HTTPS URL")

    default_port = 443 if scheme == "https" else 80
    port = ""
    if parsed.port is not None and parsed.port != default_port:
        port = f":{parsed.port}"

    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""

    return f"{scheme}://{host}{port}{path}{query}"


def validate_url(url: str, settings: object) -> str:
    """Validate a URL using Bintu's established fetcher safety rules.

    This function delegates to the scraper fetcher so URL policy remains in
    one place. It returns the normalized URL on success and raises the
    fetcher's existing ``TargetURLRejected`` error on failure.
    """
    from bintu_api.scraper.fetcher import _parse_target

    _parse_target(url, settings)
    return normalize_url(url)


def select_fetch_strategy(
    content_type: str | None,
    *,
    render_js: bool = False,
) -> str:
    """Select the appropriate fetch strategy for a classified content type.

    HTML may use direct fetching or browser rendering. Other supported types
    are reported as specialized targets for future extractors. Unknown or
    unsupported media remains unsupported.
    """
    media_class = classify_content_type(content_type)

    if media_class == "html":
        return "rendered_html" if render_js else "direct_html"

    if media_class in {"pdf", "json", "text"}:
        return f"specialized_{media_class}"

    return "unsupported"


from dataclasses import dataclass


@dataclass(frozen=True)
class ResolvedTarget:
    """Resolved identity and fetch metadata for an upstream URL."""

    requested_url: str
    normalized_url: str
    final_url: str | None = None
    canonical_url: str | None = None
    content_type: str | None = None
    content_class: str = "unsupported"
    redirect_count: int = 0
    fetch_strategy: str = "unsupported"


def resolve_target(
    url: str,
    settings: object,
    *,
    content_type: str | None = None,
    render_js: bool = False,
) -> ResolvedTarget:
    """Resolve a requested URL into a stable target contract.

    This function validates and normalizes the requested URL, then derives
    the fetch strategy from an optional upstream content type. It does not
    follow redirects or perform network I/O; those remain fetcher concerns.
    """
    normalized_url = validate_url(url, settings)
    content_class = classify_content_type(content_type)

    return ResolvedTarget(
        requested_url=url,
        normalized_url=normalized_url,
        content_type=content_type,
        content_class=content_class,
        fetch_strategy=select_fetch_strategy(
            content_type,
            render_js=render_js,
        ),
    )


def prepare_fetch_target(
    url: str,
    settings: object,
    *,
    render_js: bool = False,
) -> ResolvedTarget:
    """Validate a requested URL before robots enforcement or fetching.

    The returned target is informational for this slice. The original URL
    remains the value passed to robots, cache, and fetch collaborators so
    existing behavior and cache identity are unchanged.
    """
    return resolve_target(
        url,
        settings,
        content_type=None,
        render_js=render_js,
    )


def prepare_fetch_target(
    url: str,
    settings: object,
    *,
    render_js: bool = False,
) -> ResolvedTarget:
    """Validate a requested URL before robots enforcement or fetching.

    The returned target is informational for this slice. The original URL
    remains the value passed to robots, cache, and fetch collaborators so
    existing behavior and cache identity are unchanged.
    """
    return resolve_target(
        url,
        settings,
        content_type=None,
        render_js=render_js,
    )
