"""Streamable MCP must expose the same stable tool-error contract."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from bintu_api.mcp import TOOL_NAME
from bintu_api.scraper import TargetURLRejected
from bintu_api.settings import Settings
from main import create_app


class McpStreamableErrorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(
            Settings(
                api_key="",
                rapidapi_proxy_secret="",
                render_js_enabled=False,
            )
        )
        self.client = TestClient(self.app)
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        }

    def _call(self, arguments: dict) -> dict:
        response = self.client.post(
            "/mcp",
            headers=self.headers,
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
        self.assertIn("result", payload)
        return payload["result"]

    def test_unsafe_url_is_in_band(self) -> None:
        with patch(
            "bintu_api.routes._fetch_and_extract",
            side_effect=TargetURLRejected("private address"),
        ):
            result = self._call({"url": "http://127.0.0.1/"})

        self.assertTrue(result["isError"])
        self.assertIn("invalid_or_unsafe_url", result["content"][0]["text"])
        self.assertNotIn("http://127.0.0.1/", result["content"][0]["text"])

    def test_robots_block_is_in_band(self) -> None:
        with patch(
            "bintu_api.routes._fetch_and_extract",
            side_effect=HTTPException(
                status_code=403,
                detail={
                    "code": "blocked_by_robots",
                    "message": "Fetching this page is not permitted.",
                    "hint": "The site owner controls this.",
                },
            ),
        ):
            result = self._call({"url": "https://example.com/private"})

        self.assertTrue(result["isError"])
        self.assertIn("blocked_by_robots", result["content"][0]["text"])

    def test_robots_unreachable_is_in_band(self) -> None:
        with patch(
            "bintu_api.routes._fetch_and_extract",
            side_effect=HTTPException(
                status_code=403,
                detail={
                    "code": "robots_unreachable",
                    "message": "robots.txt could not be retrieved.",
                    "hint": "Access is denied while robots enforcement is enabled.",
                },
            ),
        ):
            result = self._call({"url": "https://example.com/page"})

        self.assertTrue(result["isError"])
        self.assertIn("robots_unreachable", result["content"][0]["text"])

    def test_render_disabled_is_in_band(self) -> None:
        result = self._call(
            {
                "url": "https://example.com/app",
                "render_js": True,
            }
        )

        self.assertTrue(result["isError"])
        self.assertIn("render_js_disabled", result["content"][0]["text"])


if __name__ == "__main__":
    unittest.main(verbosity=2)