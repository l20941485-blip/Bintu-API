"""Extraction pipeline orchestration for the REST and MCP surfaces.

This module owns the orchestration step that turns a fetched document or a
persisted cache row into the canonical ``ContextResult`` used by the public
response envelopes. It intentionally stays above transport code and below route
logic: it knows how to combine cache economics, token budgets, provenance, and
mode-specific transformations without depending on FastAPI routing or MCP JSON-RPC
formatting.
"""

from __future__ import annotations

from typing import Any

from bintu_api.context import ContextResult, extract_context
from bintu_api.settings import Settings

__all__ = [
    "extract_document",
    "run_extraction",
]


async def run_extraction(
    request: Any,
    url: str,
    *,
    mode: str = "scrape",
    max_tokens: int = 6000,
    sections: list[str] | None = None,
    cache: bool = True,
    render_js: bool = False,
    include_nav: bool = False,
    include_header: bool = False,
    include_footer: bool = False,
    identity: str | None = None,
    raw_text: str | None = None,
    content_truncated: bool = False,
    html_source_text: str | None = None,
    cache_hit: bool = False,
    cache_layer: str = "none",
    document: Any | None = None,
    settings: Settings | None = None,
    cache_economics: Any | None = None,
    extracted_at: str | None = None,
) -> ContextResult:
    """Run the existing extraction pipeline and return the canonical context result."""
    return await extract_context(
        request,
        url,
        mode=mode,
        max_tokens=max_tokens,
        sections=sections,
        cache=cache,
        render_js=render_js,
        include_nav=include_nav,
        include_header=include_header,
        include_footer=include_footer,
        identity=identity,
        raw_text=raw_text,
        content_truncated=content_truncated,
        html_source_text=html_source_text,
        cache_hit=cache_hit,
        cache_layer=cache_layer,
        document=document,
        settings=settings,
        cache_economics=cache_economics,
        extracted_at=extracted_at,
    )


async def extract_document(*args: Any, **kwargs: Any) -> ContextResult:
    """Compatibility alias for extraction pipeline consumers."""
    return await run_extraction(*args, **kwargs)
