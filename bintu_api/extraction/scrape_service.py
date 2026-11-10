"""Orchestrate the shared scrape extraction workflow.

This service owns the fetch -> robots -> cache -> extract boundary. Its
collaborators are injected by the caller, keeping this module independent of
FastAPI request objects, concrete cache implementations, and database clients.
"""

from __future__ import annotations

import asyncio
import logging

from bintu_api.database import (
    CachedMarkdown,
)
from bintu_api.extraction.builder import build_cached_markdown
from bintu_api.extraction.cache_policy import (
    compute_cache_key,
    is_cacheable,
    is_persistent_cache_enabled,
    resolve_extraction_cap,
)
from bintu_api.extraction.cacheaccess import (
    should_read_persistent_cache,
    should_write_persistent_cache,
)
from bintu_api.extraction.memory_cache import (
    read_memory_cache,
    write_memory_cache,
)
from bintu_api.extraction.persistent_cache import (
    read_persistent_cache,
    write_persistent_cache,
)
from bintu_api.extraction.request_context import ScrapeRequestContext
from bintu_api.extraction.request_policy import (
    resolve_fetch_strategy,
    validate_link_mode,
)
from bintu_api.extraction.scrape_options import ScrapeOptions
from bintu_api.scraper import FetchedHTML

logger = logging.getLogger("bintu_api.scrape")


class ScrapeService:
    """Coordinate a scrape request without owning HTTP or persistence details."""

    def __init__(
        self,
        *,
        cache,
        persistent_cache_reader,
        persistent_cache_writer,
        robots_enforcer,
        html_fetcher,
        rendered_html_fetcher,
        text_extractor,
        source_decoder,
        cache_event_logger,
    ) -> None:
        self.cache = cache
        self.persistent_cache_reader = persistent_cache_reader
        self.persistent_cache_writer = persistent_cache_writer
        self.robots_enforcer = robots_enforcer
        self.html_fetcher = html_fetcher
        self.rendered_html_fetcher = rendered_html_fetcher
        self.text_extractor = text_extractor
        self.source_decoder = source_decoder
        self.cache_event_logger = cache_event_logger

    async def _fetch_document(
        self,
        url: str,
        settings: object,
        cache_key: str,
        render_js: bool,
    ) -> FetchedHTML:
        """Enforce robots and obtain the document using the configured strategy."""
        await self.robots_enforcer(url, settings, cache_key[:12])

        strategy = resolve_fetch_strategy(render_js)
        if strategy == "rendered":
            return await self.rendered_html_fetcher(url, settings)
        return await asyncio.to_thread(
            self.html_fetcher,
            url,
            settings,
        )

    async def fetch_and_extract(
        self,
        context: ScrapeRequestContext,
        url: str,
        options: ScrapeOptions,
    ) -> tuple[FetchedHTML | None, CachedMarkdown, str]:
        """Fetch, enforce robots, consult caches, and extract markdown."""
        include_nav = options.include_nav
        include_header = options.include_header
        include_footer = options.include_footer
        render_js = options.render_js
        links = options.links
        skip_cache = options.skip_cache
        persist = options.persist
        footnote_url_policy = options.footnote_url_policy
        max_footnote_url_length = options.max_footnote_url_length
        sections = options.sections

        validate_link_mode(links)

        settings = context.settings
        extraction_cap = resolve_extraction_cap(settings)
        persistent_cache_enabled = is_persistent_cache_enabled(settings, links)
        cacheable = is_cacheable(url)
        database_client = context.database_client
        result = None
        document = None
        cache_layer = "none"
        request_id = context.request_id

        if should_read_persistent_cache(
            database_client,
            persistent_cache_enabled,
            cacheable,
            skip_cache,
            sections,
        ):
            result = await read_persistent_cache(
                database_client,
                url,
                render_js,
                include_nav,
                include_header,
                include_footer,
                self.persistent_cache_reader,
                request_id=request_id,
            )

        cache_key = compute_cache_key(render_js=options.render_js, links=options.links, url=url)

        if result is not None:
            cache_layer = "persistent"
            self.cache_event_logger(
                event="cache_hit",
                url=url,
                request_id=request_id,
                layer=cache_layer,
            )
            return document, result, cache_layer

        document = await read_memory_cache(
            self.cache,
            cache_key,
            skip_cache,
            sections,
        )

        if document is not None:
            cache_layer = "memory"
            self.cache_event_logger(
                event="cache_hit",
                url=url,
                request_id=request_id,
                layer=cache_layer,
            )
        else:
            self.cache_event_logger(
                event="cache_miss",
                url=url,
                request_id=request_id,
                layer="none",
            )

            document = await self._fetch_document(
                url,
                settings,
                cache_key,
                render_js,
            )

        extracted = self.text_extractor(
            document.body,
            extraction_cap,
            include_nav=options.include_nav,
            include_header=options.include_header,
            include_footer=options.include_footer,
            from_encoding=document.charset,
            base_url=document.final_url or url,
            links=options.links,
            footnote_url_policy=options.footnote_url_policy,
            max_footnote_url_length=options.max_footnote_url_length,
        )

        write_memory_cache(
            self.cache,
            cache_key,
            document,
            cache_layer,
            extracted.text,
        )

        result = build_cached_markdown(
            document,
            extracted,
            url,
            decode_source_text_fn=self.source_decoder,
        )

        if should_write_persistent_cache(
            database_client,
            persistent_cache_enabled,
            cacheable,
            persist,
        ):
            await write_persistent_cache(
                database_client,
                url,
                render_js,
                include_nav,
                include_header,
                include_footer,
                result,
                self.persistent_cache_writer,
                request_id=request_id,
            )

        return document, result, cache_layer










