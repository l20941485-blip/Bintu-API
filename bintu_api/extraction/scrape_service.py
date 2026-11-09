"""Orchestrate the shared scrape extraction workflow.

This service owns the fetch -> robots -> cache -> extract boundary. Its
collaborators are injected by the caller, keeping this module independent of
FastAPI request objects, concrete cache implementations, and database clients.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Literal

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

    async def fetch_and_extract(
        self,
        context: ScrapeRequestContext,
        url: str,
        *,
        include_nav: bool,
        include_header: bool,
        include_footer: bool,
        render_js: bool,
        links: Literal["inline", "footnotes", "false"] = "inline",
        skip_cache: bool = False,
        persist: bool = True,
        mode: str = "scrape",
        max_tokens: int = 6000,
        footnote_url_policy: Literal["full", "truncated"] = "truncated",
        max_footnote_url_length: int = 100,
        sections: list[str] | None = None,
    ) -> tuple[FetchedHTML | None, CachedMarkdown, str]:
        """Fetch, enforce robots, consult caches, and extract markdown."""
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

        cache_key = compute_cache_key(render_js=render_js, links=links, url=url)

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

            await self.robots_enforcer(url, settings, cache_key[:12])

            strategy = resolve_fetch_strategy(render_js)
            if strategy == "rendered":
                document = await self.rendered_html_fetcher(url, settings)
            else:
                document = await asyncio.to_thread(
                    self.html_fetcher,
                    url,
                    settings,
                )

        extracted = self.text_extractor(
            document.body,
            extraction_cap,
            include_nav=include_nav,
            include_header=include_header,
            include_footer=include_footer,
            from_encoding=document.charset,
            base_url=document.final_url or url,
            links=links,
            footnote_url_policy=footnote_url_policy,
            max_footnote_url_length=max_footnote_url_length,
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



