"""Persistent cache hit behavior and empty-row rejection."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bintu_api.database import CachedMarkdown, get_cached_markdown
from bintu_api.routes import _fetch_and_extract
from bintu_api.settings import Settings


class PersistentCacheHitTests(unittest.IsolatedAsyncioTestCase):
    def _request(self, settings: Settings):
        request = MagicMock()
        request.state.request_id = "test-request-id"

        request.app.state.settings = settings
        request.app.state.supabase_client = MagicMock()
        request.app.state.cache = MagicMock()
        request.app.state.cache.get.return_value = None
        return request

    async def test_persistent_hit_does_not_fetch_page(self) -> None:
        settings = Settings(api_key="", rapidapi_proxy_secret="")
        request = self._request(settings)

        cached = CachedMarkdown(
            markdown="# Example\n\nCached body text.",
            truncated=False,
            html_tokens=100,
            tokens_saved_estimate=42,
            limiting_factor="none",
            extracted_at="2026-10-25T00:00:00+00:00",
        )

        with patch(
            "bintu_api.routes.get_cached_markdown",
            new=AsyncMock(return_value=cached),
        ), patch(
            "bintu_api.routes.fetch_html_document",
            side_effect=AssertionError("persistent cache hit must not fetch"),
        ), patch(
            "bintu_api.routes.fetch_rendered_html_document",
            side_effect=AssertionError("persistent cache hit must not render"),
        ):
            document, result, cache_layer = await _fetch_and_extract(
                request,
                "https://example.com/article",
                include_nav=False,
                include_header=False,
                include_footer=False,
                render_js=False,
                skip_cache=False,
            )

        self.assertIsNone(document)
        self.assertEqual(cache_layer, "persistent")
        self.assertIn("Cached body text", result.markdown)
        self.assertEqual(result.tokens_saved_estimate, 42)
        self.assertEqual(result.html_tokens, 100)
        request.app.state.cache.get.assert_not_called()
        request.app.state.cache.set.assert_not_called()

    async def test_empty_cached_markdown_row_is_rejected(self) -> None:
        response = MagicMock()
        response.data = [{
            "markdown": "",
            "truncated": False,
            "html_tokens": 0,
            "tokens_saved_estimate": 0,
            "limiting_factor": "none",
            "extracted_at": "2026-10-25T00:00:00+00:00",
        }]

        builder = MagicMock()
        builder.execute = AsyncMock(return_value=response)
        builder.select.return_value = builder
        builder.eq.return_value = builder
        builder.gt.return_value = builder
        builder.limit.return_value = builder

        client = MagicMock()
        client.table.return_value = builder

        result = await get_cached_markdown(
            client,
            "https://example.com/article",
            False,
            False,
            False,
            False,
        )

        self.assertIsNone(result)
        builder.execute.assert_awaited_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
    