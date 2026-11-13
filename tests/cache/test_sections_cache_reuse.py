"""Tests for sections cache reuse behavior.

Verifies that:
- The canonical full extracted document is cached.
- A sections request may read that canonical cache entry.
- Section selection is applied after a cache hit.
- Section selectors are NOT part of the cache key.
- A cache miss fetches and extracts once, then applies selection.
- No filtered/selected response is stored under a selector-specific cache key.
"""
import asyncio
import hashlib
import unittest
from types import SimpleNamespace
from unittest import mock

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


class SectionsCacheReuseTests(unittest.TestCase):
    def patches(self):
        return (
            mock.patch(
                "bintu_api.api.scrape_adapter.fetch_html_document",
                return_value=fake_document(),
            ),
            mock.patch(
                "bintu_api.api.scrape_adapter.get_cached_markdown",
                new=mock.AsyncMock(return_value=None),
            ),
            mock.patch(
                "bintu_api.api.scrape_adapter.upsert_cached_markdown",
                new=mock.AsyncMock(),
            ),
            mock.patch(
                "bintu_api.security.auth.has_valid_proxy_secret",
                return_value=False,
            ),
        )

    def test_sections_first_request_populates_cache(self):
        """A sections cache miss fetches once and writes the canonical cache."""
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
        self.assertIsNotNone(response.selected_sections)
        self.assertEqual(response.text, "Hello world")

    def test_sections_second_request_reads_from_cache(self):
        """A second sections request reuses the canonical memory-cache entry."""
        cache = FakeCache({cache_key(): fake_document()})
        request = make_request(cache, db_client=None)
        fetch, get_cached, upsert, proxy = self.patches()

        with fetch as fetch_m, get_cached as get_m, upsert as upsert_m, proxy:
            response = run(request, sections=["Hello world"])

        self.assertFalse(get_m.called)
        self.assertEqual(cache.get_calls, 1)
        fetch_m.assert_not_called()
        self.assertEqual(response.cache_layer, "memory")
        self.assertIsNotNone(response.selected_sections)
        self.assertEqual(response.text, "Hello world")

    def test_different_selectors_same_cache_no_duplicates(self):
        """Different selectors reuse one canonical cache entry."""
        cache = FakeCache({cache_key(): fake_document()})
        request1 = make_request(cache, db_client=None)
        request2 = make_request(cache, db_client=None)
        fetch, get_cached, upsert, proxy = self.patches()

        with fetch as fetch_m, get_cached as get_m, upsert as upsert_m, proxy:
            response1 = run(request1, sections=["Section A"])
            response2 = run(request2, sections=["Section B"])

        self.assertFalse(get_m.called)
        self.assertEqual(cache.get_calls, 2)
        fetch_m.assert_not_called()
        upsert_m.assert_not_called()
        self.assertEqual(list(cache.data), [cache_key()])
        self.assertIsNotNone(response1.selected_sections)
        self.assertIsNotNone(response2.selected_sections)
