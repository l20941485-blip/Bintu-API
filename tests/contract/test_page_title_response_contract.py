"""Expose document-level page titles in REST and MCP responses."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from bintu_api.common.fetch import FetchedHTML
from bintu_api.extraction.context import ContextResult
from bintu_api.extraction.response import (
    build_mcp_envelope,
    build_rest_response,
)
from bintu_api.mcp import TOOL_OUTPUT_SCHEMA
from bintu_api.settings import Settings
from main import create_app

URL = "https://example.com/contract"
TITLE = "Example Page Title"
TIMESTAMP = "2026-01-01T00:00:00+00:00"


def make_context(title, title_source="html_title"):
    return ContextResult(
        mode="scrape",
        text="Readable example content.",
        approx_tokens=4,
        html_tokens=100,
        token_method="ceil(characters/4)",
        limiting_factor="none",
        tokens=4,
        chunk_count=1,
        cache_hit=False,
        cache_layer="none",
        source_url=URL,
        extracted_at=TIMESTAMP,
        page_title=title,
        page_title_source=title_source if title else "none",
    )


class PageTitleResponseContractTests(unittest.TestCase):
    def test_mcp_envelope_exposes_populated_title(self):
        envelope = build_mcp_envelope(make_context(TITLE), URL)

        self.assertEqual(envelope["page_title"], TITLE)
        self.assertEqual(envelope["page_title_source"], "html_title")

    def test_mcp_envelope_omits_missing_title(self):
        envelope = build_mcp_envelope(make_context(None), URL)

        self.assertNotIn("page_title", envelope)

    def test_rest_response_exposes_populated_title(self):
        response = build_rest_response(make_context(TITLE), URL)

        self.assertEqual(response["provenance"]["page_title"], TITLE)
        self.assertEqual(
            response["provenance"]["page_title_source"],
            "html_title",
        )

    def test_rest_response_omits_missing_title(self):
        response = build_rest_response(make_context(None), URL)

        self.assertNotIn("page_title", response["provenance"])

    def test_schema_declares_optional_title(self):
        properties = TOOL_OUTPUT_SCHEMA["properties"]

        self.assertIn("page_title", properties)
        self.assertNotIn("page_title", TOOL_OUTPUT_SCHEMA["required"])
        self.assertIn("page_title_source", properties)
        self.assertNotIn(
            "page_title_source",
            TOOL_OUTPUT_SCHEMA["required"],
        )


class PageTitleSurfaceTests(unittest.TestCase):
    def setUp(self):
        settings = Settings(
            api_key="page-title-contract-test-key",
            rapidapi_proxy_secret="",
            robots_mode="off",
        )

        self.app = create_app(settings)
        self.app.state.supabase_client = None
        self.app.state.rate_limiter = SimpleNamespace(check=Mock())

        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

        self.headers = {
            "X-API-Key": "page-title-contract-test-key",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        }

    def make_fetch(self, title, title_source="html_title"):
        document = FetchedHTML(
            body=(b"<html><body><main><p>Readable example content.</p></main></body></html>"),
            charset="utf-8",
            final_url=URL,
            page_title=title,
            page_title_source=title_source if title else "none",
        )

        cached = SimpleNamespace(
            markdown="Readable example content.",
            truncated=False,
            extracted_at=TIMESTAMP,
            html_tokens=100,
            tokens_saved_estimate=90,
            limiting_factor="none",
            page_title=title,
            page_title_source=title_source if title else "none",
        )

        return AsyncMock(return_value=(document, cached, "none", False))

    def call(self, surface, title, title_source="html_title"):
        fetch = self.make_fetch(title, title_source)

        with patch(
            "bintu_api.api.scrape_adapter._fetch_and_extract",
            new=fetch,
        ):
            if surface == "legacy":
                response = self.client.post(
                    "/mcp/tools/call",
                    headers=self.headers,
                    json={
                        "name": "bintu_scrape_text",
                        "arguments": {"url": URL},
                    },
                )
            else:
                response = self.client.post(
                    "/mcp",
                    headers=self.headers,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "tools/call",
                        "params": {
                            "name": "bintu_scrape_text",
                            "arguments": {"url": URL},
                        },
                    },
                )

        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()

        if surface == "streamable":
            result = result["result"]

        return result, fetch

    def test_both_surfaces_expose_populated_title(self):
        for surface in ("legacy", "streamable"):
            with self.subTest(surface=surface):
                result, _ = self.call(surface, TITLE)

                structured = result["structuredContent"]
                self.assertEqual(structured["page_title"], TITLE)
                self.assertEqual(
                    structured["page_title_source"],
                    "html_title",
                )

    def test_both_surfaces_omit_missing_title(self):
        for surface in ("legacy", "streamable"):
            with self.subTest(surface=surface):
                result, _ = self.call(surface, None)

                structured = result["structuredContent"]
                self.assertNotIn("page_title", structured)

    def test_both_surfaces_omit_title_source_without_title(self):
        for surface in ("legacy", "streamable"):
            with self.subTest(surface=surface):
                result, _ = self.call(surface, None)

                structured = result["structuredContent"]
                self.assertNotIn("page_title", structured)
                self.assertNotIn("page_title_source", structured)


if __name__ == "__main__":
    unittest.main()
