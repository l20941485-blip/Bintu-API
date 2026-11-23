"""Cache lifecycle events must distinguish hits, refreshes, and fallbacks."""

import unittest
from types import SimpleNamespace
from datetime import UTC, datetime, timedelta
from unittest import mock

from bintu_api.api import scrape_adapter as routes
from bintu_api.extraction.cache_store import CachedMarkdown
from bintu_api.extraction.memory_cache import MemoryCacheEntry
from tests.cache.test_cache_bypass import (
    URL,
    FakeCache,
    cache_key,
    fake_document,
    make_request,
)


def fetch_document(*args, **kwargs):
    return fake_document()


def make_lifecycle_request(cache, db_client=None):
    request = make_request(cache, db_client=db_client)
    request.state = SimpleNamespace(request_id="test-id")
    return request


original_build_scrape_service = routes.build_scrape_service


def _build_service_with_fake_fetcher(request):
    service = original_build_scrape_service(request)
    service.html_fetcher = fetch_document
    return service


class CacheEventLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def run_request(self, request, **kwargs):
        return await routes._fetch_and_extract(
            request,
            URL,
            include_nav=False,
            include_header=False,
            include_footer=False,
            render_js=False,
            **kwargs,
        )

    def patches(self, persistent_result=None):
        return (
            mock.patch(
                "bintu_api.api.scrape_adapter.build_scrape_service",
                side_effect=_build_service_with_fake_fetcher,
            ),
            mock.patch(
                "bintu_api.api.scrape_adapter.get_cached_markdown",
                new=mock.AsyncMock(return_value=persistent_result),
            ),
            mock.patch(
                "bintu_api.api.scrape_adapter.upsert_cached_markdown",
                new=mock.AsyncMock(),
            ),
            mock.patch(
                "bintu_api.security.auth.has_valid_proxy_secret",
                return_value=False,
            ),
            mock.patch(
                "bintu_api.api.scrape_adapter.log_cache_event"
            ),
        )

    async def test_persistent_hit_logs_cache_hit(self):
        cache = FakeCache()
        request = make_lifecycle_request(cache, db_client=object())

        fetch, get_cached, upsert, proxy, log_event = self.patches(
            persistent_result=CachedMarkdown(
                markdown="from-persistent",
                truncated=False,
            ),
        )

        with fetch, get_cached, upsert, proxy, log_event as event_logger:
            _, _, layer, _ = await self.run_request(request)

        event_logger.assert_called_once_with(
            event="cache_hit",
            url=URL,
            request_id="test-id",
            layer="persistent",
        )
        self.assertEqual(layer, "persistent")

    async def test_fresh_memory_hit_logs_cache_hit(self):
        cache = FakeCache({cache_key(): fake_document()})
        request = make_lifecycle_request(cache, db_client=None)

        fetch, get_cached, upsert, proxy, log_event = self.patches()

        with fetch, get_cached, upsert, proxy, log_event as event_logger:
            _, _, layer, _ = await self.run_request(request)

        event_logger.assert_called_once_with(
            event="cache_hit",
            url=URL,
            request_id="test-id",
            layer="memory",
        )
        self.assertEqual(layer, "memory")

    async def test_cold_miss_logs_cache_miss(self):
        cache = FakeCache()
        request = make_lifecycle_request(cache, db_client=None)

        fetch, get_cached, upsert, proxy, log_event = self.patches()

        with fetch, get_cached, upsert, proxy, log_event as event_logger:
            _, _, layer, _ = await self.run_request(request)

        event_logger.assert_called_once_with(
            event="cache_miss",
            url=URL,
            request_id="test-id",
            layer="none",
        )
        self.assertEqual(layer, "none")

    async def test_stale_memory_hit_logs_refresh_then_fallback(self):
        stale_extracted_at = (
            datetime.now(UTC) - timedelta(hours=25)
        ).isoformat()

        cache = FakeCache(
            {
                cache_key(): MemoryCacheEntry(
                    document=fake_document(),
                    extracted_at=stale_extracted_at,
                    extractor_version="1.0.0",
                    content_hash="hash",
                )
            }
        )
        request = make_lifecycle_request(cache, db_client=None)

        fetch, get_cached, upsert, proxy, log_event = self.patches()

        with (
            fetch as fetch_mock,
            get_cached,
            upsert,
            proxy,
            log_event as event_logger,
            mock.patch(
                "bintu_api.api.scrape_adapter.extract_text_result",
                side_effect=RuntimeError("synthetic refresh failure"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                await self.run_request(request)

        self.assertEqual(
            [call.kwargs["event"] for call in event_logger.call_args_list],
            ["stale_cache_refresh", "stale_cache_fallback"],
        )
        self.assertEqual(
            [call.kwargs["layer"] for call in event_logger.call_args_list],
            ["memory", "memory"],
        )
        fetch_mock.assert_awaited_once()
