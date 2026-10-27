"""REST and MCP must provide semantically stable extraction results."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from bintu_api.mcp import TOOL_NAME
from bintu_api.scraper import FetchedHTML
from bintu_api.settings import Settings
from main import create_app


MCP_CORE_ENVELOPE_FIELDS = {
    "mode",
    "tokens",
    "approx_tokens",
    "chunk_count",
    "cache_hit",
    "source_url",
    "extracted_at",
    "tokens_saved_estimate",
    "truncated",
    "chunks",
}


class CrossSurfaceEnvelopeTests(unittest.TestCase):
    def setUp(self) -> None:
        # These contract tests isolate robots retrieval from page fetching.
        robots_patcher = patch(
            "bintu_api.routes._enforce_robots",
            new=AsyncMock(return_value=None),
        )
        self.addCleanup(robots_patcher.stop)
        robots_patcher.start()
        self.url = "https://example.com/page"
        self.document = FetchedHTML(
            final_url=self.url,
            body=(
                b"<html><body><main><h1>Hello</h1>"
                b"<p>This is a sufficiently long article body.</p></main></body></html>"
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

    def test_rest_response_has_stable_shape(self) -> None:
        client = self._client()

        with self._patch_fetch():
            response = client.get(
                "/api/v1/scrape/text",
                params={"url": self.url},
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()

        for field in (
            "url",
            "text",
            "truncated",
            "cache_layer",
            "approx_tokens",
            "token_method",
            "tokens",
            "tokens_saved_estimate",
            "provenance",
        ):
            self.assertIn(field, payload)

        self.assertEqual(payload["url"], self.url)
        self.assertEqual(payload["cache_layer"], "none")
        self.assertFalse(payload["truncated"])
        self.assertGreater(payload["approx_tokens"], 0)
        self.assertEqual(payload["provenance"]["requested_url"], self.url)
        self.assertFalse(payload["provenance"]["cache"]["hit"])

    def test_legacy_mcp_envelope_has_core_fields(self) -> None:
        client = self._client()

        with self._patch_fetch():
            response = client.post(
                "/mcp/tools/call",
                json={
                    "name": TOOL_NAME,
                    "arguments": {"url": self.url},
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["isError"])

        envelope = json.loads(payload["content"][0]["text"])
        for field in MCP_CORE_ENVELOPE_FIELDS:
            self.assertIn(field, envelope)

        self.assertEqual(envelope["mode"], "scrape")
        self.assertFalse(envelope["cache_hit"])
        self.assertEqual(envelope["source_url"], self.url)
        self.assertIsInstance(envelope["chunks"], list)
        self.assertGreater(envelope["approx_tokens"], 0)

    def test_streamable_mcp_envelope_has_core_fields(self) -> None:
        client = self._client()

        with self._patch_fetch():
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
                        "arguments": {"url": self.url},
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("result", payload)

        result = payload["result"]
        self.assertFalse(result["isError"])
        self.assertIn("structuredContent", result)

        envelope = result["structuredContent"]
        for field in MCP_CORE_ENVELOPE_FIELDS:
            self.assertIn(field, envelope)

        self.assertEqual(envelope["mode"], "scrape")
        self.assertFalse(envelope["cache_hit"])
        self.assertEqual(envelope["source_url"], self.url)
        self.assertIsInstance(envelope["chunks"], list)
        self.assertGreater(envelope["approx_tokens"], 0)

    def test_mcp_structured_content_matches_text_envelope(self) -> None:
        client = self._client()

        with self._patch_fetch():
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
                        "arguments": {"url": self.url},
                    },
                },
            )

        result = response.json()["result"]
        text_envelope = json.loads(result["content"][0]["text"])
        structured_envelope = result["structuredContent"]

        self.assertEqual(text_envelope, structured_envelope)

    def test_rest_and_mcp_agree_on_core_semantics(self) -> None:
        rest_client = self._client()
        mcp_client = self._client()

        with self._patch_fetch():
            rest_response = rest_client.get(
                "/api/v1/scrape/text",
                params={"url": self.url},
            )

        with self._patch_fetch():
            mcp_response = mcp_client.post(
                "/mcp/tools/call",
                json={
                    "name": TOOL_NAME,
                    "arguments": {"url": self.url},
                },
            )

        rest = rest_response.json()
        mcp = json.loads(mcp_response.json()["content"][0]["text"])

        self.assertEqual(rest["url"], mcp["source_url"])
        self.assertEqual(rest["text"], mcp["chunks"][0]["text"])
        self.assertEqual(rest["truncated"], mcp["truncated"])
        self.assertEqual(rest["approx_tokens"], mcp["approx_tokens"])
        self.assertEqual(rest["tokens"], mcp["tokens"])
        self.assertEqual(rest["tokens_saved_estimate"], mcp["tokens_saved_estimate"])
        self.assertEqual(rest["cache_layer"] != "none", mcp["cache_hit"])


if __name__ == "__main__":
    unittest.main(verbosity=2)