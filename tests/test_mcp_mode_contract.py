"""MCP extraction modes must be stable and semantically correct."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from bintu_api.mcp import TOOL_NAME
from bintu_api.scraper import FetchedHTML
from bintu_api.settings import Settings
from main import create_app


class McpModeContractTests(unittest.TestCase):
    def setUp(self) -> None:
        # These contract tests isolate robots retrieval from page fetching.
        robots_patcher = patch(
            "bintu_api.routes._enforce_robots",
            new=AsyncMock(return_value=None),
        )
        self.addCleanup(robots_patcher.stop)
        robots_patcher.start()
        self.url = "https://example.com/article"
        paragraph = (
            "<p>Bintu provides a stable extraction contract for AI agents. "
            "This paragraph adds enough readable content to exceed a small "
            "summarization budget. Each sentence contributes additional "
            "characters and approximate tokens to the resulting document.</p>"
        )
        self.document = FetchedHTML(
            final_url=self.url,
            body=(
                b"<html><body><main>"
                b"<h1>Bintu mode contract</h1>"
                + (paragraph.encode() * 10)
                + b"</main></body></html>"
            ),
            charset="utf-8",
        )

    def _client(self) -> TestClient:
        app = create_app(
            Settings(
                api_key="",
                rapidapi_proxy_secret="",
                render_js_enabled=False,
            )
        )
        return TestClient(app)

    def _patch_fetch(self):
        return patch(
            "bintu_api.routes.fetch_html_document",
            return_value=self.document,
        )

    def _streamable_call(self, client: TestClient, arguments: dict) -> dict:
        response = client.post(
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
                    "arguments": {"url": self.url, **arguments},
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("result", payload)
        return payload["result"]

    def test_scrape_mode_returns_single_chunk(self) -> None:
        client = self._client()

        with self._patch_fetch():
            result = self._streamable_call(client, {"mode": "scrape"})

        envelope = result["structuredContent"]
        self.assertEqual(envelope["mode"], "scrape")
        self.assertEqual(envelope["chunk_count"], 1)
        self.assertEqual(len(envelope["chunks"]), 1)
        self.assertFalse(result["isError"])

    def test_chunk_mode_returns_chunk_envelope(self) -> None:
        client = self._client()

        with self._patch_fetch():
            result = self._streamable_call(
                client,
                {"mode": "chunk", "max_tokens": 100},
            )

        envelope = result["structuredContent"]
        self.assertEqual(envelope["mode"], "chunk")
        self.assertGreaterEqual(envelope["chunk_count"], 1)
        self.assertEqual(len(envelope["chunks"]), envelope["chunk_count"])

        for index, chunk in enumerate(envelope["chunks"]):
            self.assertEqual(chunk["index"], index)
            self.assertIn("text", chunk)
            self.assertIn("tokens", chunk)

    def test_chunked_alias_is_normalized(self) -> None:
        client = self._client()

        with self._patch_fetch():
            result = self._streamable_call(
                client,
                {"mode": "chunked", "max_tokens": 100},
            )

        envelope = result["structuredContent"]
        self.assertEqual(envelope["mode"], "chunk")

    def test_summarize_mode_truncates_to_budget(self) -> None:
        client = self._client()

        with self._patch_fetch():
            result = self._streamable_call(
                client,
                {"mode": "summarize", "max_tokens": 100},
            )

        envelope = result["structuredContent"]
        self.assertEqual(envelope["mode"], "summarize")
        self.assertLessEqual(envelope["approx_tokens"], 100)
        self.assertTrue(envelope["truncated"])

    def test_legacy_mcp_chunked_alias_is_normalized(self) -> None:
        client = self._client()

        with self._patch_fetch():
            response = client.post(
                "/mcp/tools/call",
                json={
                    "name": TOOL_NAME,
                    "arguments": {
                        "url": self.url,
                        "mode": "chunked",
                        "max_tokens": 100,
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["isError"])

        envelope = json.loads(payload["content"][0]["text"])
        self.assertEqual(envelope["mode"], "chunk")

    def test_invalid_mode_is_rejected(self) -> None:
        client = self._client()

        response = client.post(
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
                    "arguments": {
                        "url": self.url,
                        "mode": "not-a-mode",
                    },
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("error", payload)
        self.assertEqual(payload["error"]["code"], -32602)

    def test_max_tokens_below_minimum_is_rejected(self) -> None:
        client = self._client()

        response = client.post(
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
                    "arguments": {
                        "url": self.url,
                        "mode": "summarize",
                        "max_tokens": 10,
                    },
                },
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("error", payload)
        self.assertEqual(payload["error"]["code"], -32602)
        self.assertIn("max_tokens", payload["error"]["message"])


if __name__ == "__main__":
    unittest.main(verbosity=2)