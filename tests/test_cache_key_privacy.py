"""Cache keys must be private, deterministic, and render-mode aware."""

from __future__ import annotations

import hashlib
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bintu_api.routes import _fetch_and_extract
from bintu_api.scraper import FetchedHTML
from bintu_api.settings import Settings


class CacheKeyPrivacyTests(unittest.IsolatedAsyncioTestCase):
    def _request(self) -> MagicMock:
        request = MagicMock()
        request.app.state.settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            render_js_enabled=False,
        )
        request.app.state.supabase_client = None
        request.app.state.cache = MagicMock()
        request.app.state.cache.get.return_value = None
        request.state.request_id = "cache-key-test"
        return request

    def _document(self) -> FetchedHTML:
        return FetchedHTML(
            final_url="https://example.com/page",
            body=b"<html><body><main><h1>Hello</h1><p>World</p></main></body></html>",
            charset="utf-8",
        )

    async def test_cache_key_is_sha256_and_hides_url(self) -> None:
        request = self._request()
        url = "https://example.com/private?page=secret-token"
        document = self._document()

        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=document,
        ):
            await _fetch_and_extract(
                request,
                url,
                include_nav=False,
                include_header=False,
                include_footer=False,
                render_js=False,
                skip_cache=False,
            )

        cache = request.app.state.cache
        cache.set.assert_called_once()
        cache_key = cache.set.call_args.args[0]

        self.assertEqual(len(cache_key), 64)
        self.assertRegex(cache_key, r"^[0-9a-f]{64}$")
        self.assertNotIn(url, cache_key)
        self.assertNotIn("secret-token", cache_key)

    async def test_cache_key_depends_on_render_mode(self) -> None:
        request = self._request()
        url = "https://example.com/page"
        document = self._document()
        keys: list[str] = []

        def capture_key(_key: str, _document: FetchedHTML) -> None:
            keys.append(_key)

        request.app.state.cache.set.side_effect = capture_key

        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=document,
        ):
            await _fetch_and_extract(
                request,
                url,
                include_nav=False,
                include_header=False,
                include_footer=False,
                render_js=False,
                skip_cache=False,
            )

            with patch(
                "bintu_api.routes.fetch_rendered_html_document",
                new=AsyncMock(return_value=document),
            ):
                await _fetch_and_extract(
                    request,
                    url,
                    include_nav=False,
                    include_header=False,
                    include_footer=False,
                    render_js=True,
                    skip_cache=False,
                )

        self.assertEqual(len(keys), 2)
        self.assertNotEqual(keys[0], keys[1])

        expected_plain = hashlib.sha256(f"0:{url}".encode()).hexdigest()
        expected_rendered = hashlib.sha256(f"1:{url}".encode()).hexdigest()
        self.assertEqual(keys[0], expected_plain)
        self.assertEqual(keys[1], expected_rendered)

    async def test_skip_cache_bypasses_cache_read(self) -> None:
        request = self._request()
        url = "https://example.com/page"
        document = self._document()

        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=document,
        ) as fetch:
            await _fetch_and_extract(
                request,
                url,
                include_nav=False,
                include_header=False,
                include_footer=False,
                render_js=False,
                skip_cache=True,
            )

        request.app.state.cache.get.assert_not_called()
        fetch.assert_called_once()

    async def test_skip_cache_still_checks_robots(self) -> None:
        request = self._request()
        url = "https://example.com/page"
        document = self._document()

        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=document,
        ), patch(
            "bintu_api.routes._enforce_robots",
            new=AsyncMock(),
        ) as robots:
            await _fetch_and_extract(
                request,
                url,
                include_nav=False,
                include_header=False,
                include_footer=False,
                render_js=False,
                skip_cache=True,
            )

        robots.assert_awaited_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)