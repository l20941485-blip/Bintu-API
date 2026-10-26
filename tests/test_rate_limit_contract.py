"""Rate-limit contract parity across REST and both MCP surfaces."""

from __future__ import annotations

import unittest

from fastapi import HTTPException
from fastapi.testclient import TestClient

from bintu_api.mcp import TOOL_NAME
from bintu_api.settings import Settings
from main import create_app


class ExplodingRateLimiter:
    def check(self, identity: str) -> None:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "burst_rate_limit_exceeded",
                "message": "Limit is 1 requests per 60 seconds.",
            },
            headers={"Retry-After": "42"},
        )


class RateLimitContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(
            Settings(
                api_key="",
                rapidapi_proxy_secret="",
                render_js_enabled=False,
            )
        )
        self.app.state.rate_limiter = ExplodingRateLimiter()
        self.client = TestClient(self.app)

    def _assert_rate_limited(self, response) -> None:
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers.get("Retry-After"), "42")
        payload = response.json()
        self.assertEqual(
            payload["detail"]["code"],
            "burst_rate_limit_exceeded",
        )
        self.assertNotIn("identity", response.text.lower())

    def test_rest_returns_429_with_retry_after(self) -> None:
        response = self.client.get(
            "/api/v1/scrape/text",
            params={"url": "https://example.com/page"},
        )
        self._assert_rate_limited(response)

    def test_legacy_mcp_returns_429_with_retry_after(self) -> None:
        response = self.client.post(
            "/mcp/tools/call",
            json={
                "name": TOOL_NAME,
                "arguments": {"url": "https://example.com/page"},
            },
        )
        self._assert_rate_limited(response)

    def test_streamable_mcp_returns_429_with_retry_after(self) -> None:
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
                    "arguments": {"url": "https://example.com/page"},
                },
            },
        )
        self._assert_rate_limited(response)


if __name__ == "__main__":
    unittest.main(verbosity=2)