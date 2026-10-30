import asyncio
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlparse

from tests.test_cache_bypass import (
    URL,
    FakeCache,
    cache_key,
    fake_document,
    make_request,
)
from bintu_api import routes
from bintu_api.routes import redact_cache_url


class RedactCacheUrlTests(unittest.TestCase):
    def test_redacts_credential_query_values(self):
        redacted = redact_cache_url(
            "https://example.com/page?token=secret-token&id=42"
        )

        parsed = urlparse(redacted)
        query = parse_qs(parsed.query)

        self.assertEqual(query["token"], ["[REDACTED]"])
        self.assertEqual(query["id"], ["42"])
        self.assertNotIn("secret-token", redacted)

    def test_redacts_all_known_credential_parameters(self):
        redacted = redact_cache_url(
            "https://example.com/"
            "?access_token=a&api_key=b&apikey=c&key=d"
            "&secret=e&password=f&session=g&sessionid=h"
            "&auth=i&authorization=j"
        )

        query = parse_qs(urlparse(redacted).query)

        for name in (
            "access_token",
            "api_key",
            "apikey",
            "key",
            "secret",
            "password",
            "session",
            "sessionid",
            "auth",
            "authorization",
        ):
            self.assertEqual(query[name], ["[REDACTED]"])

    def test_preserves_path_and_noncredential_query(self):
        redacted = redact_cache_url(
            "https://example.com/docs/page?utm_source=newsletter&page=2"
        )

        self.assertIn("/docs/page", redacted)
        self.assertIn("utm_source=newsletter", redacted)
        self.assertIn("page=2", redacted)

    def test_handles_url_without_query(self):
        self.assertEqual(
            redact_cache_url("https://example.com/docs/page"),
            "https://example.com/docs/page",
        )


class PersistenceOptOutTests(unittest.TestCase):
    def patches(self):
        return (
            mock.patch.object(routes, "fetch_html_document", return_value=fake_document()),
            mock.patch.object(
                routes,
                "get_cached_markdown",
                new=mock.AsyncMock(return_value=None),
            ),
            mock.patch.object(routes, "upsert_cached_markdown", new=mock.AsyncMock()),
            mock.patch.object(routes, "has_valid_proxy_secret", return_value=False),
        )

    def run_scrape(self, request, url, persist):
        return asyncio.run(
            routes._scrape_text(
                request,
                url,
                False,
                False,
                False,
                "test-id",
                False,
                False,
                persist,
            )
        )

    def test_persist_false_skips_persistent_write(self):
        cache = FakeCache()
        request = make_request(cache, db_client=object())
        fetch, get_cached, upsert, proxy = self.patches()

        with fetch as fetch_m, get_cached, upsert as upsert_m, proxy:
            response = self.run_scrape(request, URL, persist=False)

        fetch_m.assert_called_once()
        upsert_m.assert_not_called()
        self.assertEqual(response.cache_layer, "none")
        self.assertIn(cache_key(), cache.data)

    def test_persist_true_does_not_write_credential_url(self):
        url = "https://example.com/page?token=secret-token&id=42"
        cache = FakeCache()
        request = make_request(cache, db_client=object())
        fetch, get_cached, upsert, proxy = self.patches()

        with (
            fetch as fetch_m,
            get_cached as get_cached_m,
            upsert as upsert_m,
            proxy,
        ):
            response = self.run_scrape(request, url, persist=True)

        get_cached_m.assert_not_called()
        upsert_m.assert_not_called()
        self.assertEqual(response.cache_layer, "none")




if __name__ == "__main__":
    unittest.main()
