"""Tests for the /api/v1/scrape/chunks endpoint."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from bintu_api.routes import scrape_chunks
from bintu_api.settings import Settings


class ScrapeChunksEndpointTests(unittest.IsolatedAsyncioTestCase):
    def _request(self, render_js_enabled: bool = False):
        settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            render_js_enabled=render_js_enabled,
        )

        request = MagicMock()
        request.state.request_id = "test-request-id"
        request.app.state.settings = settings
        request.app.state.supabase_client = MagicMock()
        request.app.state.cache = MagicMock()
        request.app.state.cache.get.return_value = None
        return request

    def _payload(self, render_js: bool = False):
        payload = MagicMock()
        payload.url = "https://example.com/article"
        payload.include_nav = False
        payload.include_header = False
        payload.include_footer = False
        payload.render_js = render_js
        return payload

    async def test_invalid_low_token_budget_is_rejected(self) -> None:
        request = self._request()
        payload = self._payload()

        with patch("bintu_api.routes.verify_api_access"), patch(
            "bintu_api.routes.rate_limit_identity",
            return_value="test-client",
        ):
            with self.assertRaises(HTTPException) as caught:
                await scrape_chunks(
                    request,
                    payload,
                    max_tokens=99,
                    skip_cache=False,
                    persist=False,
                )

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(
            caught.exception.detail["code"],
            "invalid_token_budget",
        )

    async def test_invalid_high_token_budget_is_rejected(self) -> None:
        request = self._request()
        payload = self._payload()

        with patch("bintu_api.routes.verify_api_access"), patch(
            "bintu_api.routes.rate_limit_identity",
            return_value="test-client",
        ):
            with self.assertRaises(HTTPException) as caught:
                await scrape_chunks(
                    request,
                    payload,
                    max_tokens=50001,
                    skip_cache=False,
                    persist=False,
                )

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(
            caught.exception.detail["code"],
            "invalid_token_budget",
        )

    async def test_disabled_javascript_rendering_is_rejected(self) -> None:
        request = self._request(render_js_enabled=False)
        payload = self._payload(render_js=True)

        with patch("bintu_api.routes.verify_api_access"), patch(
            "bintu_api.routes.rate_limit_identity",
            return_value="test-client",
        ):
            with self.assertRaises(HTTPException) as caught:
                await scrape_chunks(
                    request,
                    payload,
                    max_tokens=1000,
                    skip_cache=False,
                    persist=False,
                )

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(
            caught.exception.detail["code"],
            "render_js_disabled",
        )

    async def test_valid_request_returns_chunked_response(self) -> None:
        request = self._request()
        payload = self._payload()

        result = MagicMock()
        result.markdown = (
            "First paragraph about web scraping. "
            "Second paragraph about token budgets. "
        ) * 50
        result.html_tokens = 500
        result.truncated = False
        result.extracted_at = "2026-10-29T00:00:00+00:00"

        with patch("bintu_api.routes.verify_api_access"), patch(
            "bintu_api.routes.rate_limit_identity",
            return_value="test-client",
        ), patch(
            "bintu_api.routes._scrape_chunks",
            new=AsyncMock(return_value=(None, result, "none")),
        ):
            response = await scrape_chunks(
                request,
                payload,
                max_tokens=200,
                skip_cache=False,
                persist=False,
            )

        self.assertTrue(response.split)
        self.assertGreater(response.chunk_count, 1)
        self.assertEqual(len(response.chunks), response.chunk_count)
        self.assertEqual(response.chunks[0].index, 0)

        for chunk in response.chunks:
            self.assertTrue(chunk.text.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
    
