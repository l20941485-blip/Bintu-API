"""Token Tax engine tests: aliases, unified envelope, 401 upgrade_url, metering header."""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from bintu_api.context import normalize_mode
from bintu_api.mcp import TOOL_INPUT_SCHEMA, ToolArguments
from bintu_api.scraper import FetchedHTML
from bintu_api.settings import Settings
from main import create_app


class TokenMeteringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(Settings(api_key="", rapidapi_proxy_secret=""))
        self.client = TestClient(self.app)

    def rpc(self, method: str, params: dict | None = None, request_id: int = 1):
        return self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
        )

    def test_normalize_mode_maps_chunked_case_insensitive(self) -> None:
        self.assertEqual(normalize_mode("chunked"), "chunk")
        self.assertEqual(normalize_mode(" CHUNKED "), "chunk")
        self.assertEqual(normalize_mode("Chunked"), "chunk")
        self.assertEqual(normalize_mode("chunk"), "chunk")
        self.assertEqual(normalize_mode("scrape"), "scrape")

    def test_tool_arguments_accepts_chunked_alias(self) -> None:
        args = ToolArguments.model_validate({"url": "https://example.com", "mode": "chunked"})
        self.assertEqual(args.mode, "chunk")

    def test_tool_arguments_accepts_chunk_token_budget_alias(self) -> None:
        args = ToolArguments.model_validate(
            {"url": "https://example.com", "mode": "chunk", "chunk_token_budget": 500}
        )
        self.assertEqual(args.max_tokens, 500)

    def test_tool_arguments_canonical_max_tokens_wins_on_conflict(self) -> None:
        args = ToolArguments.model_validate(
            {
                "url": "https://example.com",
                "max_tokens": 1000,
                "chunk_token_budget": 500,
            }
        )
        self.assertEqual(args.max_tokens, 1000)

    def test_schema_documents_pitch_aliases(self) -> None:
        mode_desc = TOOL_INPUT_SCHEMA["properties"]["mode"]["description"]
        tokens_desc = TOOL_INPUT_SCHEMA["properties"]["max_tokens"]["description"]
        self.assertIn("chunked", mode_desc)
        self.assertIn("chunk_token_budget", tokens_desc)
        # Strict enum stays canonical so validators don't reject installed clients.
        self.assertEqual(
            TOOL_INPUT_SCHEMA["properties"]["mode"]["enum"],
            ["scrape", "chunk", "summarize"],
        )

    def test_scrape_returns_unified_envelope(self) -> None:
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=b"<main>Hello world metering</main>", charset=None),
        ):
            response = self.rpc(
                "tools/call",
                {"name": "bintu_scrape_text", "arguments": {"url": "https://example.com"}},
            )
        self.assertEqual(response.status_code, 200)
        envelope = json.loads(response.json()["result"]["content"][0]["text"])
        for key in (
            "mode",
            "tokens",
            "chunk_count",
            "cache_hit",
            "source_url",
            "tokens_saved_estimate",
            "truncated",
            "chunks",
        ):
            self.assertIn(key, envelope)
        self.assertEqual(envelope["mode"], "scrape")
        self.assertGreater(envelope["tokens"], 0)

    def test_chunk_alias_returns_budgeted_chunks(self) -> None:
        long_text = "Sentence one. " * 200
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=f"<main>{long_text}</main>", charset=None),
        ):
            response = self.rpc(
                "tools/call",
                {
                    "name": "bintu_scrape_text",
                    "arguments": {
                        "url": "https://example.com",
                        "mode": "chunked",
                        "chunk_token_budget": 100,
                    },
                },
            )
        self.assertEqual(response.status_code, 200)
        envelope = json.loads(response.json()["result"]["content"][0]["text"])
        self.assertEqual(envelope["mode"], "chunk")
        self.assertGreater(envelope["chunk_count"], 1)
        for chunk in envelope["chunks"]:
            self.assertLessEqual(chunk["tokens"], 100)

    def test_metering_header_present(self) -> None:
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=b"<main>Header check</main>", charset=None),
        ):
            response = self.rpc(
                "tools/call",
                {"name": "bintu_scrape_text", "arguments": {"url": "https://example.com"}},
            )
        self.assertIn("x-token-usage", response.headers)
        self.assertIn("tokens=", response.headers["x-token-usage"])

    def test_unauthorized_call_carries_upgrade_url(self) -> None:
        app = create_app(
            Settings(api_key="owner-key", rapidapi_proxy_secret="", mcp_api_key="claude-key")
        )
        client = TestClient(app)
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "bintu_scrape_text",
                    "arguments": {"url": "https://example.com"},
                },
            },
        )
        self.assertEqual(response.status_code, 401)
        data = response.json()["error"]["data"]
        self.assertEqual(data["code"], "premium_required")
        self.assertEqual(data["upgrade_url"], "https://mcpize.com")
        self.assertIn("https://mcpize.com", data["hint"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
