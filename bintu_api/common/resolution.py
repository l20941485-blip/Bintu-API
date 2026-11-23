"""Pure URL-resolution classification contracts.

This module intentionally performs no network I/O. Fetching, redirect
validation, SSRF protection, and canonical-URL extraction remain owned by
their existing modules.
"""

from __future__ import annotations


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
