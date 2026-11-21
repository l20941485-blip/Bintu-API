"""REST and MCP must expose the same semantic chunk retrieval contract."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from bintu_api.mcp import TOOL_NAME
from bintu_api.scraper.fetcher import FetchedHTML
from bintu_api.settings import Settings
from main import create_app

URL = "https://example.com/chunk-parity"

HTML = (
    b"<html><body><main>"
    b"<h1>Overview</h1>"
    b"<p>This is the first sufficiently long paragraph for semantic chunking.</p>"
    b"<h2>Details</h2>"
    b"<p>This is the second sufficiently long paragraph for semantic chunking.</p>"
    b"</main></body></html>"
)

SHARED_SEMANTIC_CHUNK_FIELDS = (
    "index",
    "text",
    "approx_tokens",
    "tokens",
    "chunk_strategy",
    "chunk_id",
    "heading_path",
    "section_index",
    "contains_code",
    "contains_table",
    "contains_links",
    "link_count",
    "source_url",
    "final_url",
    "content_sha256",
    "extracted_at",
)


class ChunkProvenanceSurfaceParityTests(unittest.TestCase):
    def setUp(self) -> None:
        robots_patcher = patch(
            "bintu_api.api.scrape_adapter._enforce_robots",
            new=unittest.mock.AsyncMock(return_value=None),
        )
        robots_patcher.start()
        self.addCleanup(robots_patcher.stop)

        self.document = FetchedHTML(
            final_url=URL,
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

    def _rest_chunks(self, client: TestClient) -> list[dict]:
        with self._patch_fetch:
            response = client.post(
                "/api/v1/scrape/chunks",
                params={
                    "max_tokens": 100,
                    "chunk_strategy": "semantic",
                },
                json={"url": URL},
            )

        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["chunks"]

    def _mcp_chunks(self, client: TestClient) -> list[dict]:
        with self._patch_fetch:
            response = client.post(
                "/mcp/tools/call",
                json={
                    "name": TOOL_NAME,
                    "arguments": {
                        "url": URL,
                        "mode": "chunk",
                        "max_tokens": 100,
                        "chunk_strategy": "semantic",
                    },
                },
            )

        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertFalse(payload["isError"], payload)

        envelope = json.loads(payload["content"][0]["text"])
        return envelope["chunks"]

    def test_rest_and_mcp_agree_on_shared_semantic_chunk_contract(self) -> None:
        client = self._client()

        rest_chunks = self._rest_chunks(client)
        mcp_chunks = self._mcp_chunks(client)

        self.assertGreater(len(rest_chunks), 0)
        self.assertEqual(len(rest_chunks), len(mcp_chunks))

        for rest_chunk, mcp_chunk in zip(
            rest_chunks,
            mcp_chunks,
            strict=True,
        ):
            for field in SHARED_SEMANTIC_CHUNK_FIELDS:
                self.assertEqual(
                    rest_chunk[field],
                    mcp_chunk[field],
                    f"{field} differs between REST and MCP",
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
