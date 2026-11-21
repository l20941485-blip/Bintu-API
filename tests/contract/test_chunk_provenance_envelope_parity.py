"""REST and MCP must expose the same response-level extraction provenance."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from bintu_api.mcp import TOOL_NAME
from bintu_api.scraper.fetcher import FetchedHTML
from bintu_api.settings import Settings
from main import create_app

REQUESTED_URL = "https://example.com/envelope-parity"
FINAL_URL = "https://example.com/envelope-final"

HTML = (
    b"<html><body><main>"
    b"<h1>Envelope parity</h1>"
    b"<p>This page contains enough readable text for chunking.</p>"
    b"</main></body></html>"
)

ENVELOPE_FIELDS = (
    "source_url",
    "extracted_at",
)


class ChunkProvenanceEnvelopeParityTests(unittest.TestCase):
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

    def test_rest_and_mcp_agree_on_response_provenance(self) -> None:
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
        rest_envelope = rest_response.json()

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

        mcp_envelope = json.loads(payload["content"][0]["text"])

        for field in ENVELOPE_FIELDS:
            self.assertIn(field, rest_envelope)
            self.assertIn(field, mcp_envelope)
            self.assertEqual(
                rest_envelope[field],
                mcp_envelope[field],
                f"{field} differs between REST and MCP envelopes",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
