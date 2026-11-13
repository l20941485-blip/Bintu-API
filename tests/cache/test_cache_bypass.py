"""Test Cache Bypass for Bintu.

This module owns a focused responsibility within the service and must remain isolated from unrelated transport or persistence concerns.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""
import asyncio
import hashlib
import unittest
from types import SimpleNamespace
from unittest import mock

from bintu_api.extraction.cache_store import CachedMarkdown
from bintu_api.settings import Settings

URL = "https://example.com/page"
HTML = b"<html><body><article><p>Hello world</p></article></body></html>"


class FakeCache:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.get_calls = 0

    def get(self, key):
        self.get_calls += 1
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value


def fake_document():
    return SimpleNamespace(body=HTML, charset="utf-8", final_url=URL)


def make_request(cache, db_client=None):
    settings = Settings(api_key="", rapidapi_proxy_secret="", robots_mode="off")
    state = SimpleNamespace(
        settings=settings,
        rate_limiter=SimpleNamespace(check=lambda identity: None),
        supabase_client=db_client,
        cache=cache,
    )
    return SimpleNamespace(app=SimpleNamespace(state=state), headers={})


def cache_key():
    return hashlib.sha256(f"0:inline:{URL}".encode()).hexdigest()


def run(request, skip_cache=False, sections=None):
    from bintu_api.api.routes.extract import _scrape_text as scrape_text
    return asyncio.run(
        scrape_text(
            request,
            URL,
            False,
            False,
            False,
            "test-id",
            False,
            links="inline",
            skip_cache=skip_cache,
            sections=sections,
        )
    )


class CacheBypassTests(unittest.TestCase):
    def patches(self, persistent_result=None):
        return (
            mock.patch("bintu_api.api.scrape_adapter.fetch_html_document", return_value=fake_document()),
            mock.patch(
                "bintu_api.api.scrape_adapter.get_cached_markdown",
                new=mock.AsyncMock(return_value=persistent_result),
            ),
            mock.patch("bintu_api.api.scrape_adapter.upsert_cached_markdown", new=mock.AsyncMock()),
            mock.patch("bintu_api.security.auth.has_valid_proxy_secret", return_value=False),
        )

    def test_sections_reuse_persistent_and_memory_cache(self):
        """Sections requests reuse the canonical full-page cache."""
        # First request: persistent miss, memory miss, fetch, canonical write.
        cache = FakeCache()
        request = make_request(cache, db_client=object())
        fetch, get_cached, upsert, proxy = self.patches()

        with fetch as fetch_m, get_cached as get_m, upsert as upsert_m, proxy:
            response = run(request, sections=["Hello world"])

        self.assertEqual(get_m.call_count, 1)
        self.assertEqual(cache.get_calls, 1)
        fetch_m.assert_called_once()
        self.assertIn(cache_key(), cache.data)
        self.assertEqual(response.cache_layer, "none")
        self.assertEqual(response.text, "Hello world")

        # Second request: no persistent client, memory hit, no fetch.
        cache2 = FakeCache({cache_key(): fake_document()})
        request2 = make_request(cache2, db_client=None)
        fetch2, get_cached2, upsert2, proxy2 = self.patches()

        with fetch2 as fetch_m2, get_cached2 as get_m2, upsert2 as upsert_m2, proxy2:
            response2 = run(request2, sections=["Hello world"])

        self.assertFalse(get_m2.called)
        self.assertEqual(cache2.get_calls, 1)
        fetch_m2.assert_not_called()
        self.assertEqual(response2.cache_layer, "memory")
        self.assertEqual(response2.text, "Hello world")

    def test_skip_cache_reads_no_cache_but_still_writes(self):
        """skip_cache=True should bypass cache reads but still write.

        This test preserves the original behavior from the old test.
        """
        cache = FakeCache({cache_key(): fake_document()})
        request = make_request(cache, db_client=object())
        fetch, get_cached, upsert, proxy = self.patches()

        with fetch as fetch_m, get_cached as get_m, upsert as upsert_m, proxy:
            response = run(request, skip_cache=True)

        get_m.assert_not_called()
        self.assertEqual(cache.get_calls, 0)
        fetch_m.assert_called_once()
        upsert_m.assert_called_once()
        self.assertEqual(response.cache_layer, "none")

    def test_persistent_hit_does_not_fetch(self):
        """Persistent cache hit should not fetch upstream.

        This test preserves the original behavior from the old test.
        """
        cache = FakeCache()
        request = make_request(cache, db_client=object())
        fetch, get_cached, upsert, proxy = self.patches(
            persistent_result=CachedMarkdown(
                markdown="from-persistent", truncated=False
            ),
        )

        with fetch as fetch_m, get_cached, upsert, proxy:
            response = run(request)

        fetch_m.assert_not_called()
        self.assertEqual(response.text, "from-persistent")
        self.assertEqual(response.cache_layer, "persistent")

    def test_memory_hit_does_not_fetch(self):
        """Memory cache hit should not fetch upstream.

        This test preserves the original behavior from the old test.
        """
        cache = FakeCache({cache_key(): fake_document()})
        request = make_request(cache, db_client=None)
        fetch, get_cached, upsert, proxy = self.patches()

        with fetch as fetch_m, get_cached, upsert, proxy:
            response = run(request)

        fetch_m.assert_not_called()
        self.assertEqual(response.cache_layer, "memory")

    def test_cold_miss_fetches(self):
        """Cold cache miss should fetch and extract once.

        This test preserves the original behavior from the old test.
        """
        cache = FakeCache()
        request = make_request(cache, db_client=None)
        fetch, get_cached, upsert, proxy = self.patches()

        with fetch as fetch_m, get_cached, upsert, proxy:
            response = run(request)

        fetch_m.assert_called_once()
        self.assertEqual(response.cache_layer, "none")
