"""Phase 2 cross-surface contract tests.

REST, legacy MCP, and Streamable MCP intentionally expose different transport
shapes, but they must agree on the shared extraction semantics: text, URL,
token accounting, cache state, truncation, and savings.
"""


import json
import unittest
from unittest.mock import AsyncMock, patch


from fastapi.testclient import TestClient


from bintu_api.database import CachedMarkdown
from bintu_api.mcp import TOOL_NAME
from bintu_api.scraper import FetchedHTML
from bintu_api.settings import Settings
from main import create_app


from unittest import mock


from bintu_api.robots import RobotsDecision


_robots_patch = mock.patch(
    "bintu_api.routes.robots_decision",
    return_value=RobotsDecision(allowed=True, reason="disabled in tests", checked=False),
)


def setUpModule():
    _robots_patch.start()


def tearDownModule():
    _robots_patch.stop()


HTML = b"<html><body><main>Cross-surface contract text</main></body></html>"
EXPECTED_TEXT = "Cross-surface contract text"
PARITY_URL = "https://example.com/parity"

MCP_ENVELOPE_FIELDS = {
    "deduplicated_count",
    "mode",
    "tokens",
    "approx_tokens",
    "html_tokens",
    "token_method",
    "limiting_factor",
    "chunk_count",
    "cache_hit",
    "cache_layer",
    "source_url",
    "extracted_at",
    "tokens_saved_estimate",
    "truncated",
    "split",
    "chunks",
}


class CrossSurfaceContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(Settings(api_key="", rapidapi_proxy_secret=""))
        self.client = TestClient(self.app)

    def _reset_caches(self) -> None:
        """Ensure every surface performs a fresh extraction during parity tests."""
        self.app.state.cache.clear()

    def _rest_response(self, url: str) -> dict:
        self._reset_caches()
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=HTML, charset=None),
        ):
            response = self.client.get(
                "/api/v1/scrape/text",
                params={"url": url},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["text"], EXPECTED_TEXT)
        return body

    def _legacy_mcp_envelope(self, url: str) -> dict:
        self._reset_caches()
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=HTML, charset=None),
        ):
            response = self.client.post(
                "/mcp/tools/call",
                json={
                    "name": TOOL_NAME,
                    "arguments": {"url": url, "mode": "scrape"},
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["isError"])
        return json.loads(payload["content"][0]["text"])

    def _streamable_mcp_envelope(self, url: str) -> dict:
        self._reset_caches()
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=HTML, charset=None),
        ):
            response = self.client.post(
                "/mcp",
                headers={
                    "Accept": "application/json",
                    "MCP-Protocol-Version": "2025-11-25",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": TOOL_NAME,
                        "arguments": {"url": url, "mode": "scrape"},
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("error", payload)
        result = payload["result"]
        self.assertFalse(result["isError"])
        return result["structuredContent"]

    def _assert_valid_mcp_scrape_envelope(self, envelope: dict) -> None:
        self.assertEqual(set(envelope), MCP_ENVELOPE_FIELDS)
        self.assertEqual(envelope["mode"], "scrape")
        self.assertEqual(envelope["chunks"][0]["text"], EXPECTED_TEXT)
        self.assertEqual(envelope["chunk_count"], 1)
        self.assertEqual(envelope["split"], False)
        self.assertEqual(envelope["truncated"], False)
        self.assertEqual(envelope["limiting_factor"], "none")
        self.assertEqual(envelope["token_method"], "ceil(characters/4)")
        self.assertEqual(envelope["tokens"], envelope["approx_tokens"])
        self.assertEqual(envelope["chunk_count"], len(envelope["chunks"]))
        self.assertEqual(
            envelope["tokens_saved_estimate"],
            max(0, envelope["html_tokens"] - envelope["approx_tokens"]),
        )
        self.assertGreater(envelope["approx_tokens"], 0)
        self.assertGreater(envelope["html_tokens"], envelope["approx_tokens"])
        self.assertGreater(envelope["tokens_saved_estimate"], 0)

    def test_rest_returns_valid_scrape_response(self) -> None:
        response = self._rest_response("https://example.com/rest-contract")

        self.assertEqual(response["url"], "https://example.com/rest-contract")
        self.assertEqual(response["text"], EXPECTED_TEXT)
        self.assertEqual(response["truncated"], False)
        self.assertEqual(response["cache_layer"], "none")
        self.assertEqual(response["token_method"], "ceil(characters/4)")
        self.assertEqual(response["tokens"], response["approx_tokens"])
        self.assertGreater(response["approx_tokens"], 0)
        self.assertGreater(response["tokens_saved_estimate"], 0)
        self.assertIn("provenance", response)

    def test_legacy_mcp_returns_valid_unified_envelope(self) -> None:
        envelope = self._legacy_mcp_envelope("https://example.com/legacy-mcp-contract")
        self._assert_valid_mcp_scrape_envelope(envelope)
        self.assertEqual(envelope["cache_hit"], False)
        self.assertEqual(envelope["cache_layer"], "none")
        self.assertEqual(envelope["source_url"], "https://example.com/legacy-mcp-contract")

    def test_streamable_mcp_returns_valid_unified_envelope(self) -> None:
        envelope = self._streamable_mcp_envelope(
            "https://example.com/streamable-mcp-contract"
        )
        self._assert_valid_mcp_scrape_envelope(envelope)
        self.assertEqual(envelope["cache_hit"], False)
        self.assertEqual(envelope["cache_layer"], "none")
        self.assertEqual(
            envelope["source_url"],
            "https://example.com/streamable-mcp-contract",
        )

    def test_all_surfaces_share_the_same_extraction_semantics(self) -> None:
        rest = self._rest_response(PARITY_URL)
        legacy = self._legacy_mcp_envelope(PARITY_URL)
        streamable = self._streamable_mcp_envelope(PARITY_URL)

        self._assert_valid_mcp_scrape_envelope(legacy)
        self._assert_valid_mcp_scrape_envelope(streamable)

        # REST and MCP use different transport shapes, but must agree on the
        # semantic extraction result.
        self.assertEqual(rest["text"], legacy["chunks"][0]["text"])
        self.assertEqual(rest["text"], streamable["chunks"][0]["text"])

        self.assertEqual(rest["url"], legacy["source_url"])
        self.assertEqual(rest["url"], streamable["source_url"])

        self.assertEqual(rest["truncated"], legacy["truncated"])
        self.assertEqual(rest["truncated"], streamable["truncated"])

        self.assertEqual(rest["cache_layer"], legacy["cache_layer"])
        self.assertEqual(rest["cache_layer"], streamable["cache_layer"])

        self.assertEqual(rest["approx_tokens"], legacy["approx_tokens"])
        self.assertEqual(rest["approx_tokens"], streamable["approx_tokens"])

        self.assertEqual(rest["tokens"], legacy["tokens"])
        self.assertEqual(rest["tokens"], streamable["tokens"])

        self.assertEqual(rest["token_method"], legacy["token_method"])
        self.assertEqual(rest["token_method"], streamable["token_method"])

        self.assertEqual(
            rest["tokens_saved_estimate"],
            legacy["tokens_saved_estimate"],
        )
        self.assertEqual(
            rest["tokens_saved_estimate"],
            streamable["tokens_saved_estimate"],
        )

    def test_persistent_cache_preserves_extraction_economics(self) -> None:
        self.app.state.supabase_client = object()
        cached = CachedMarkdown(
            markdown="<main>Cached economics text</main>",
            truncated=False,
            html_tokens=2737,
            tokens_saved_estimate=2183,
            limiting_factor="none",
            extracted_at="2026-10-25T18:39:35.350374+00:00",
        )

        with (
            patch(
                "bintu_api.routes.get_cached_markdown",
                new=AsyncMock(return_value=cached),
            ),
            patch("bintu_api.routes.fetch_html_document") as fetch,
        ):
            response = self.client.post(
                "/mcp",
                headers={
                    "Accept": "application/json",
                    "MCP-Protocol-Version": "2025-11-25",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": TOOL_NAME,
                        "arguments": {
                            "url": "https://example.com/cached-economics",
                            "mode": "scrape",
                        },
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertNotIn("error", payload)
        envelope = payload["result"]["structuredContent"]

        self.assertEqual(envelope["cache_hit"], True)
        self.assertEqual(envelope["cache_layer"], "persistent")
        self.assertEqual(envelope["html_tokens"], 2737)
        self.assertEqual(envelope["tokens_saved_estimate"], 2183)
        self.assertEqual(
            envelope["extracted_at"],
            "2026-10-25T18:39:35.350374+00:00",
        )
        self.assertEqual(envelope["truncated"], False)
        self.assertEqual(envelope["limiting_factor"], "none")
        fetch.assert_not_called()

    def test_persistent_cache_reuses_the_original_timestamp(self) -> None:
        self.app.state.supabase_client = object()
        cached = CachedMarkdown(
            markdown="<main>Cached timestamp text</main>",
            truncated=False,
            html_tokens=1000,
            tokens_saved_estimate=800,
            limiting_factor="none",
            extracted_at="2026-10-25T19:00:00.000000+00:00",
        )

        with patch(
            "bintu_api.routes.get_cached_markdown",
            new=AsyncMock(return_value=cached),
        ):
            response = self.client.post(
                "/mcp/tools/call",
                json={
                    "name": TOOL_NAME,
                    "arguments": {
                        "url": "https://example.com/cached-timestamp",
                        "mode": "scrape",
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        envelope = json.loads(response.json()["content"][0]["text"])
        self.assertEqual(
            envelope["extracted_at"],
            "2026-10-25T19:00:00.000000+00:00",
        )
        self.assertEqual(envelope["cache_hit"], True)
        self.assertEqual(envelope["cache_layer"], "persistent")


if __name__ == "__main__":
    unittest.main(verbosity=2)
