import asyncio
import hashlib
import unittest
from types import SimpleNamespace
from unittest import mock

from bintu_api import routes
from bintu_api.database import CachedMarkdown
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
    return hashlib.sha256(f"0:{URL}".encode()).hexdigest()


def run(request, skip_cache=False):
    return asyncio.run(
        routes._scrape_text(request, URL, False, False, False, "test-id", False, skip_cache)
    )


class CacheBypassTests(unittest.TestCase):
    def patches(self):
        return (
            mock.patch.object(routes, "fetch_html_document", return_value=fake_document()),
            mock.patch.object(
                routes,
                "get_cached_markdown",
                new=mock.AsyncMock(
                    return_value=CachedMarkdown(markdown="from-persistent", truncated=False)
                ),
            ),
            mock.patch.object(routes, "upsert_cached_markdown", new=mock.AsyncMock()),
            mock.patch.object(routes, "has_valid_proxy_secret", return_value=False),
        )

    def test_skip_cache_reads_no_cache_but_still_writes(self):
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
        cache = FakeCache()
        request = make_request(cache, db_client=object())
        fetch, get_cached, upsert, proxy = self.patches()
        with fetch as fetch_m, get_cached, upsert, proxy:
            response = run(request)
        fetch_m.assert_not_called()
        self.assertEqual(response.text, "from-persistent")
        self.assertEqual(response.cache_layer, "persistent")

    def test_memory_hit_does_not_fetch(self):
        cache = FakeCache({cache_key(): fake_document()})
        request = make_request(cache, db_client=None)
        fetch, get_cached, upsert, proxy = self.patches()
        with fetch as fetch_m, get_cached, upsert, proxy:
            response = run(request)
        fetch_m.assert_not_called()
        self.assertEqual(response.cache_layer, "memory")

    def test_cold_miss_fetches(self):
        cache = FakeCache()
        request = make_request(cache, db_client=None)
        fetch, get_cached, upsert, proxy = self.patches()
        with fetch as fetch_m, get_cached, upsert, proxy:
            response = run(request)
        fetch_m.assert_called_once()
        self.assertEqual(response.cache_layer, "none")


if __name__ == "__main__":
    unittest.main()