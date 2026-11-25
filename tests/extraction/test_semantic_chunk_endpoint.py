"""Contract tests for semantic chunking on the REST chunks endpoint."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException

from bintu_api.api.routes.chunk import scrape_chunks
from bintu_api.settings import Settings


class SemanticChunkEndpointTests(unittest.IsolatedAsyncioTestCase):
    def _request(self) -> MagicMock:
        settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            render_js_enabled=False,
        )

        request = MagicMock()
        request.state.request_id = "test-request-id"
        request.app.state.settings = settings
        request.app.state.supabase_client = MagicMock()
        request.app.state.cache = MagicMock()
        request.app.state.cache.get.return_value = None
        return request

    def _payload(self) -> MagicMock:
        payload = MagicMock()
        payload.url = "https://example.com/docs"
        payload.include_nav = False
        payload.include_header = False
        payload.include_footer = False
        payload.render_js = False
        return payload

    def _result(self) -> MagicMock:
        result = MagicMock()
        result.markdown = (
            "# Guide\n\n"
            "Intro text.\n\n"
            "## Authentication\n\n"
            "Use an API key.\n\n"
            "## Rate limits\n\n"
            "Requests are limited.\n"
        )
        result.html_tokens = 500
        result.truncated = False
        result.extracted_at = "2026-11-17T00:00:00+00:00"
        result.content_hash = "test-content-sha256"
        result.page_title = "Example Guide"
        result.content_fingerprint = "sha256:test-content-fingerprint"
        return result

    async def test_default_chunk_strategy_is_sequential(self) -> None:
        request = self._request()
        payload = self._payload()
        result = self._result()

        with (
            patch("bintu_api.api.scrape_adapter.verify_api_access"),
            patch(
                "bintu_api.api.scrape_adapter.rate_limit_identity",
                return_value="test-client",
            ),
            patch(
                "bintu_api.api.routes.chunk._scrape_chunks",
                new=AsyncMock(return_value=(None, result, "none", False)),
            ),
        ):
            response = await scrape_chunks(
                request,
                payload,
                max_tokens=1000,
                skip_cache=False,
                persist=False,
            )

        self.assertEqual(response.mode, "chunk")
        self.assertGreater(response.chunk_count, 0)

        for chunk in response.chunks:
            self.assertEqual(chunk.chunk_strategy, "sequential")
            self.assertIsNone(chunk.chunk_id)
            self.assertEqual(chunk.heading_path, [])

    async def test_semantic_chunk_strategy_returns_metadata(self) -> None:
        request = self._request()
        payload = self._payload()
        result = self._result()

        with (
            patch("bintu_api.api.scrape_adapter.verify_api_access"),
            patch(
                "bintu_api.api.scrape_adapter.rate_limit_identity",
                return_value="test-client",
            ),
            patch(
                "bintu_api.api.routes.chunk._scrape_chunks",
                new=AsyncMock(return_value=(None, result, "none", False)),
            ),
        ):
            response = await scrape_chunks(
                request,
                payload,
                max_tokens=100,
                skip_cache=False,
                persist=False,
                chunk_strategy="semantic",
            )

        self.assertEqual(response.mode, "chunk")
        self.assertGreater(response.chunk_count, 0)

        for chunk in response.chunks:
            self.assertEqual(chunk.chunk_strategy, "semantic")
            self.assertTrue(chunk.chunk_id.startswith("sha256:"))
            self.assertIsInstance(chunk.heading_path, list)
            self.assertEqual(chunk.source_url, "https://example.com/docs")
            self.assertEqual(chunk.final_url, "https://example.com/docs")
            self.assertEqual(
                chunk.extracted_at,
                "2026-11-17T00:00:00+00:00",
            )

    async def test_semantic_chunks_preserve_heading_boundaries(self) -> None:
        request = self._request()
        payload = self._payload()
        result = self._result()

        with (
            patch("bintu_api.api.scrape_adapter.verify_api_access"),
            patch(
                "bintu_api.api.scrape_adapter.rate_limit_identity",
                return_value="test-client",
            ),
            patch(
                "bintu_api.api.routes.chunk._scrape_chunks",
                new=AsyncMock(return_value=(None, result, "none", False)),
            ),
        ):
            response = await scrape_chunks(
                request,
                payload,
                max_tokens=100,
                skip_cache=False,
                persist=False,
                chunk_strategy="semantic",
            )

        texts = [chunk.text for chunk in response.chunks]

        self.assertTrue(any(text.startswith("# Guide") for text in texts))
        self.assertTrue(any(text.startswith("## Authentication") for text in texts))
        self.assertTrue(any(text.startswith("## Rate limits") for text in texts))

    async def test_invalid_overlap_budget_is_rejected(self) -> None:
        request = self._request()
        payload = self._payload()

        with (
            patch("bintu_api.api.scrape_adapter.verify_api_access"),
            patch(
                "bintu_api.api.scrape_adapter.rate_limit_identity",
                return_value="test-client",
            ),
            self.assertRaises(HTTPException) as caught,
        ):
            await scrape_chunks(
                request,
                payload,
                max_tokens=100,
                skip_cache=False,
                persist=False,
                chunk_strategy="semantic",
                overlap_tokens=100,
            )

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(
            caught.exception.detail["code"],
            "invalid_overlap_budget",
        )
        self.assertEqual(
            caught.exception.detail["hint"],
            "Set overlap_tokens between 0 and max_tokens - 1.",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
