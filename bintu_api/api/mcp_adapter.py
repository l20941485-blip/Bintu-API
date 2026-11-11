"""MCP-facing application adapter.

This module is the stable boundary between MCP transport and the scraper and
extraction implementation packages. MCP transport modules must depend on this
adapter rather than importing scraper or extraction internals directly.
"""

from __future__ import annotations

from bintu_api.api.scrape_adapter import fetch_and_extract
from bintu_api.extraction.cache import build_cache_economics
from bintu_api.extraction.context import (
    _decode_source_text as decode_source_text,
)
from bintu_api.extraction.context import (
    normalize_mode,
)
from bintu_api.extraction.pipeline import run_extraction
from bintu_api.extraction.response import build_mcp_envelope
from bintu_api.scraper.fetcher import (
    PayloadTooLarge,
    TargetURLRejected,
    TooManyRedirects,
    UnsupportedContentEncoding,
    UnsupportedMediaType,
    UpstreamHTTPError,
    UpstreamRenderError,
)

__all__ = [
    "PayloadTooLarge",
    "TargetURLRejected",
    "TooManyRedirects",
    "UnsupportedContentEncoding",
    "UnsupportedMediaType",
    "UpstreamHTTPError",
    "UpstreamRenderError",
    "build_cache_economics",
    "build_mcp_envelope",
    "decode_source_text",
    "fetch_and_extract",
    "normalize_mode",
    "run_extraction",
]