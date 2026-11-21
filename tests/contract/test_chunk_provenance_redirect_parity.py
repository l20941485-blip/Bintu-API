"""REST and MCP must preserve requested and final URL semantics for redirects."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from bintu_api.mcp import TOOL_NAME
from bintu_api.scraper.fetcher import FetchedHTML
from bintu_api.settings import Settings
from main import create_app

REQUESTED_URL = "https://example.com/original"
FINAL_URL = "https://example.com/final"

HTML = (
    b"<html><body><main>"
    b"<h1>Redirected page</h1>"
    b"<p>This paragraph is long enough for semantic chunking.</p>"
    b"</main></body></html>"
)


class ChunkProvenanceRedirectParityTests(unittest.TestCase):
    def setUp(self) -> None:
        robots_patcher = patch(
            "bintu_api.api.scrape_adapter._enforce_robots",
            new=unittest.mock.AsyncMock(return_value=None),
        )
        robots_patcher.start()
        self.addCleanup(robots_patcher.stop)

        self.document = FetchedHTML(
            final_url=FINAL_URL,
            body=HTML,
            charset="utf-8",
        )
        self._patch_fetch = patch(
            "bintu_api.api.scrape_adapter.fetch_html_document",
            return_value=self.document,
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

    def test_rest_and_mcp_preserve_requested_and_final_urls(self) -> None:
        client = self._client()

        with self._patch_fetch:
            rest_response = client.post(
                "/api/v1/scrape/chunks",
                params={
                    "max_tokens": 100,
                    "chunk_strategy": "semantic",
                },
                json={"url": REQUESTED_URL},
            )

        self.assertEqual(rest_response.status_code, 200, rest_response.text)
        rest_chunks = rest_response.json()["chunks"]
        self.assertGreater(len(rest_chunks), 0)

        with self._patch_fetch:
            mcp_response = client.post(
                "/mcp/tools/call",
                json={
                    "name": TOOL_NAME,
                    "arguments": {
                        "url": REQUESTED_URL,
                        "mode": "chunk",
                        "max_tokens": 100,
                        "chunk_strategy": "semantic",
                    },
                },
            )

        self.assertEqual(mcp_response.status_code, 200, mcp_response.text)
        payload = mcp_response.json()
        self.assertFalse(payload["isError"], payload)

        envelope = json.loads(payload["content"][0]["text"])
        mcp_chunks = envelope["chunks"]
        self.assertGreater(len(mcp_chunks), 0)

        for rest_chunk, mcp_chunk in zip(
            rest_chunks,
            mcp_chunks,
            strict=True,
        ):
            self.assertEqual(
                rest_chunk["source_url"],
                REQUESTED_URL,
                "REST source_url must preserve the requested URL",
            )
            self.assertEqual(
                rest_chunk["final_url"],
                FINAL_URL,
                "REST final_url must expose the redirect destination",
            )
            self.assertEqual(
                mcp_chunk["source_url"],
                REQUESTED_URL,
                "MCP source_url must preserve the requested URL",
            )
            self.assertEqual(
                mcp_chunk["final_url"],
                FINAL_URL,
                "MCP final_url must expose the redirect destination",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
