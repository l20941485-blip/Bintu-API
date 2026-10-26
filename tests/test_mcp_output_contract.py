"""Validate successful MCP outputs and legacy cache-argument forwarding."""

from __future__ import annotations

import copy
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from bintu_api.mcp import TOOL_NAME, TOOL_OUTPUT_SCHEMA
from bintu_api.scraper import FetchedHTML
from bintu_api.settings import Settings
from main import create_app


URL = "https://example.com/contract"

TEXT = " ".join(
    f"Sentence {index} contains readable example content."
    for index in range(40)
)

HTML = (
    "<html><body><main><p>"
    + TEXT
    + "</p></main></body></html>"
).encode("utf-8")


class MCPOutputContractTests(unittest.TestCase):
    def setUp(self) -> None:
        settings = Settings(
            api_key="mcp-output-contract-test-key",
            rapidapi_proxy_secret="",
            robots_mode="off",
        )

        self.app = create_app(settings)
        self.app.state.supabase_client = None
        self.app.state.rate_limiter = SimpleNamespace(check=Mock())

        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

        self.headers = {
            "X-API-Key": "mcp-output-contract-test-key",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        }

        Draft202012Validator.check_schema(TOOL_OUTPUT_SCHEMA)
        self.validator = Draft202012Validator(TOOL_OUTPUT_SCHEMA)

    def fetch_result(self, cache_layer="none"):
        document = FetchedHTML(
            body=HTML,
            charset="utf-8",
            final_url=URL,
        )

        cached = SimpleNamespace(
            markdown=TEXT,
            truncated=False,
            extracted_at="2026-10-26T17:00:00+00:00",
            html_tokens=1000,
            tokens_saved_estimate=200,
            limiting_factor="none",
        )

        if cache_layer == "persistent":
            document = None

        return document, cached, cache_layer

    def call(self, surface, arguments, cache_layer="none"):
        fetch = AsyncMock(
            return_value=self.fetch_result(cache_layer),
        )

        with patch(
            "bintu_api.routes._fetch_and_extract",
            new=fetch,
        ):
            if surface == "legacy":
                response = self.client.post(
                    "/mcp/tools/call",
                    headers=self.headers,
                    json={
                        "name": TOOL_NAME,
                        "arguments": arguments,
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
                            "name": TOOL_NAME,
                            "arguments": arguments,
                        },
                    },
                )

        self.assertEqual(response.status_code, 200, response.text)

        result = response.json()
        if surface == "streamable":
            self.assertNotIn("error", result, result)
            result = result["result"]

        self.assertFalse(result["isError"], result)
        fetch.assert_awaited_once()

        return result, fetch

    def assert_valid_result(self, result):
        self.assertIn("structuredContent", result)

        structured = result["structuredContent"]
        serialized = json.loads(result["content"][0]["text"])

        self.assertEqual(structured, serialized)
        self.validator.validate(structured)

        self.assertEqual(
            structured["tokens"],
            structured["approx_tokens"],
        )
        self.assertEqual(
            structured["chunk_count"],
            len(structured["chunks"]),
        )

        for index, chunk in enumerate(structured["chunks"]):
            self.assertEqual(chunk["index"], index)
            self.assertEqual(
                chunk["tokens"],
                chunk["approx_tokens"],
            )

        return structured

    def test_schema_is_valid(self):
        Draft202012Validator.check_schema(TOOL_OUTPUT_SCHEMA)
        self.assertNotIn(
            "content",
            TOOL_OUTPUT_SCHEMA["required"],
        )
        self.assertIn(
            "chunks",
            TOOL_OUTPUT_SCHEMA["required"],
        )

    def test_both_surfaces_validate_in_every_mode(self):
        for surface in ("legacy", "streamable"):
            for mode in ("scrape", "chunk", "summarize"):
                with self.subTest(surface=surface, mode=mode):
                    result, _ = self.call(
                        surface,
                        {
                            "url": URL,
                            "mode": mode,
                            "max_tokens": 100,
                        },
                    )

                    structured = self.assert_valid_result(result)
                    self.assertEqual(structured["mode"], mode)

                    if mode == "chunk":
                        self.assertGreater(
                            structured["chunk_count"],
                            1,
                        )

                    if mode == "summarize":
                        self.assertTrue(structured["truncated"])

    def test_both_surfaces_validate_persistent_cache_results(self):
        for surface in ("legacy", "streamable"):
            with self.subTest(surface=surface):
                result, _ = self.call(
                    surface,
                    {"url": URL},
                    cache_layer="persistent",
                )

                structured = self.assert_valid_result(result)
                self.assertTrue(structured["cache_hit"])
                self.assertEqual(
                    structured["cache_layer"],
                    "persistent",
                )
                self.assertEqual(
                    structured["tokens_saved_estimate"],
                    200,
                )

    def test_both_surfaces_forward_cache_false_as_skip_cache(self):
        for surface in ("legacy", "streamable"):
            with self.subTest(surface=surface):
                result, fetch = self.call(
                    surface,
                    {
                        "url": URL,
                        "cache": False,
                    },
                )

                self.assert_valid_result(result)
                self.assertIs(
                    fetch.await_args.kwargs["skip_cache"],
                    True,
                )

    def test_both_surfaces_keep_default_cache_reads_enabled(self):
        for surface in ("legacy", "streamable"):
            with self.subTest(surface=surface):
                _, fetch = self.call(
                    surface,
                    {"url": URL},
                )

                self.assertIs(
                    fetch.await_args.kwargs["skip_cache"],
                    False,
                )

    def test_both_discovery_surfaces_advertise_shared_schema(self):
        legacy = self.client.get(
            "/mcp/tools",
            headers=self.headers,
        )
        self.assertEqual(legacy.status_code, 200, legacy.text)

        streamable = self.client.post(
            "/mcp",
            headers=self.headers,
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            },
        )
        self.assertEqual(
            streamable.status_code,
            200,
            streamable.text,
        )

        tools = [
            legacy.json()["tools"][0],
            streamable.json()["result"]["tools"][0],
        ]

        for tool in tools:
            with self.subTest(tool=tool["name"]):
                self.assertEqual(
                    tool["outputSchema"],
                    TOOL_OUTPUT_SCHEMA,
                )

    def test_schema_rejects_wrong_token_type(self):
        result, _ = self.call(
            "streamable",
            {"url": URL},
        )

        invalid = copy.deepcopy(result["structuredContent"])
        invalid["tokens"] = "not-an-integer"

        with self.assertRaises(ValidationError):
            self.validator.validate(invalid)

    def test_schema_rejects_missing_chunks(self):
        result, _ = self.call(
            "streamable",
            {"url": URL},
        )

        invalid = copy.deepcopy(result["structuredContent"])
        invalid.pop("chunks")

        with self.assertRaises(ValidationError):
            self.validator.validate(invalid)

    def test_schema_rejects_wrong_chunk_text_type(self):
        result, _ = self.call(
            "streamable",
            {"url": URL},
        )

        invalid = copy.deepcopy(result["structuredContent"])
        invalid["chunks"][0]["text"] = 123

        with self.assertRaises(ValidationError):
            self.validator.validate(invalid)


if __name__ == "__main__":
    unittest.main(verbosity=2)