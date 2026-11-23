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
