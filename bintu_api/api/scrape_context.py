"""Adapt HTTP request state to the request-agnostic scrape context."""

from __future__ import annotations

from fastapi import Request

from bintu_api.extraction.request_context import ScrapeRequestContext


def build_scrape_request_context(request: Request) -> ScrapeRequestContext:
    """Read request-scoped context without constructing scrape dependencies."""
    return ScrapeRequestContext(
        settings=request.app.state.settings,
        database_client=getattr(request.app.state, "supabase_client", None),
        request_id=getattr(getattr(request, "state", None), "request_id", None),
    )
