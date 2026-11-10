"""Request-agnostic extraction service boundary.

Builds the scrape service from explicit collaborators and executes it using
ScrapeRequestContext and ScrapeOptions. HTTP request adaptation remains in
bintu_api.api.routes.common; this module does not import the route layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from bintu_api.extraction.request_context import ScrapeRequestContext
from bintu_api.extraction.scrape_options import ScrapeOptions
from bintu_api.extraction.scrape_service import ScrapeService


@dataclass(frozen=True)
class ScrapeDependencies:
    """Collaborators required to construct a request-scoped scrape service."""

    cache: object
    persistent_cache_reader: object
    persistent_cache_writer: object
    robots_enforcer: object
    html_fetcher: object
    rendered_html_fetcher: object
    text_extractor: object
    source_decoder: object
    cache_event_logger: object


def build_scrape_service(
    dependencies: ScrapeDependencies,
) -> ScrapeService:
    """Build a scrape service from explicitly injected collaborators."""
    return ScrapeService(
        cache=dependencies.cache,
        persistent_cache_reader=dependencies.persistent_cache_reader,
        persistent_cache_writer=dependencies.persistent_cache_writer,
        robots_enforcer=dependencies.robots_enforcer,
        html_fetcher=dependencies.html_fetcher,
        rendered_html_fetcher=dependencies.rendered_html_fetcher,
        text_extractor=dependencies.text_extractor,
        source_decoder=dependencies.source_decoder,
        cache_event_logger=dependencies.cache_event_logger,
    )


async def fetch_and_extract_from_context(
    context: ScrapeRequestContext,
    url: str,
    options: ScrapeOptions,
    *,
    dependencies: ScrapeDependencies,
    service: ScrapeService | None = None,
) -> tuple[object | None, object, str]:
    """Run the scrape workflow using request-agnostic collaborators."""
    resolved_service = service or build_scrape_service(dependencies)
    return await resolved_service.fetch_and_extract(context, url, options)
