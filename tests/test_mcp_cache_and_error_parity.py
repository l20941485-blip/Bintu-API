"""MCP cache bypass and upstream access-denial parity with REST."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from bintu_api.mcp import TOOL_NAME
from bintu_api.scraper import UpstreamHTTPError
from bintu_api.settings import Settings
from main import create_app


class McpCacheAndErrorParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(
            Settings(
                api_key="",
                rapidapi_proxy_secret="",
                render_js_enabled=False,
            )
        )
        self.client = TestClient(self.app)

    def _call_tool(self, arguments: dict) -> dict:
        response = self.client.post(
            "/mcp",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": TOOL_NAME,
                    "arguments": arguments,
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        return payload["result"]["structuredContent"]

    def _post_tool_call(self, arguments: dict):
        return self.client.post(
            "/mcp",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": TOOL_NAME,
                    "arguments": arguments,
                },
            },
        )

    def test_cache_false_bypasses_cache_read(self) -> None:
        cached_row = type(
            "CachedMarkdown",
            (),
            {
                "markdown": "cached",
                "truncated": False,
                "html_tokens": 10,
                "tokens_saved_estimate": 0,
                "limiting_factor": "none",
                "extracted_at": "2026-01-01T00:00:00Z",
            },
        )()

        with patch(
            "bintu_api.routes._fetch_and_extract",
            new=AsyncMock(
                return_value=(None, cached_row, "none")
            ),
        ) as fetch:
            envelope = self._call_tool(
                {
                    "url": "https://example.com/page",
                    "cache": False,
                }
            )

        self.assertFalse(envelope["cache_hit"])
        self.assertEqual(envelope["cache_layer"], "none")
        self.assertTrue(fetch.await_args.kwargs["skip_cache"])

    def test_cache_true_does_not_bypass_cache_read(self) -> None:
        cached_row = type(
            "CachedMarkdown",
            (),
            {
                "markdown": "cached",
                "truncated": False,
                "html_tokens": 10,
                "tokens_saved_estimate": 0,
                "limiting_factor": "none",
                "extracted_at": "2026-01-01T00:00:00Z",
            },
        )()

        with patch(
            "bintu_api.routes._fetch_and_extract",
            new=AsyncMock(
                return_value=(None, cached_row, "persistent")
            ),
        ) as fetch:
            self._call_tool(
                {
                    "url": "https://example.com/page",
                    "cache": True,
                }
            )

        self.assertFalse(fetch.await_args.kwargs["skip_cache"])

    def test_upstream_403_maps_to_access_denied(self) -> None:
        with patch(
            "bintu_api.routes._fetch_and_extract",
            new=AsyncMock(
                side_effect=UpstreamHTTPError(403, "Forbidden")
            ),
        ):
            response = self._post_tool_call(
                {"url": "https://example.com/page"}
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        text = payload["result"]["content"][0]["text"]

        self.assertIn("upstream_access_denied", text)
        self.assertIn("HTTP 403", text)

    def test_upstream_429_maps_to_access_denied(self) -> None:
        with patch(
            "bintu_api.routes._fetch_and_extract",
            new=AsyncMock(
                side_effect=UpstreamHTTPError(
                    429, "Too Many Requests"
                )
            ),
        ):
            response = self._post_tool_call(
                {"url": "https://example.com/page"}
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        text = payload["result"]["content"][0]["text"]

        self.assertIn("upstream_access_denied", text)
        self.assertIn("HTTP 429", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)