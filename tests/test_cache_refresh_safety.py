"""Failed or empty refreshes must preserve cached raw HTML."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest import mock

from bintu_api import routes
from tests.test_cache_bypass import (
    URL, FakeCache, cache_key, fake_document, make_request,
)


class CacheRefreshSafetyTests(unittest.TestCase):
    def refresh(self, request):
        return asyncio.run(routes._fetch_and_extract(
            request, URL,
            include_nav=False,
            include_header=False,
            include_footer=False,
            render_js=False,
            skip_cache=True,
        ))

    def test_extraction_failure_preserves_memory_entry(self):
        old_document = fake_document()
        fresh_document = fake_document()
        cache = FakeCache({cache_key(): old_document})
        request = make_request(cache)

        with mock.patch.object(
            routes, "fetch_html_document", return_value=fresh_document
        ), mock.patch.object(
            routes, "extract_text_result",
            side_effect=RuntimeError("synthetic extraction failure"),
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic"):
                self.refresh(request)

        self.assertIs(cache.data[cache_key()], old_document)
        self.assertEqual(cache.get_calls, 0)

    def test_empty_extraction_preserves_memory_entry(self):
        old_document = fake_document()
        cache = FakeCache({cache_key(): old_document})
        request = make_request(cache)

        with mock.patch.object(
            routes, "fetch_html_document", return_value=fake_document()
        ), mock.patch.object(
            routes, "extract_text_result",
            return_value=SimpleNamespace(text="   ", truncated=False),
        ):
            self.refresh(request)

        self.assertIs(cache.data[cache_key()], old_document)

    def test_successful_refresh_replaces_memory_entry(self):
        old_document = fake_document()
        fresh_document = fake_document()
        cache = FakeCache({cache_key(): old_document})
        request = make_request(cache)

        with mock.patch.object(
            routes, "fetch_html_document", return_value=fresh_document
        ):
            _, result, layer = self.refresh(request)

        self.assertIs(cache.data[cache_key()], fresh_document)
        self.assertTrue(result.markdown.strip())
        self.assertEqual(layer, "none")
        self.assertEqual(cache.get_calls, 0)


if __name__ == "__main__":
    unittest.main()
