"""Deterministic output contract tests for Bintu's current behavior.

Locks the existing, shipped contract without implementing new features:

- MCP tool name, description, annotations, input / output schema
- Error-code taxonomy and normalize_error_code
- normalize_mode
- ContextResult provenance and cache-economics fields
- REST / MCP response-envelope fields
- Streamable MCP tool-error shape: HTTP 200, isError=true,
  structured upstream_rate_limited details

These tests do NOT assert byte-for-byte upstream HTML content, and they do NOT
implement heading/section selection, budget_strategy, section_budgets,
max_age, revalidate, JavaScript rendering, new arguments, or new error codes.
"""

from __future__ import annotations

import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from bintu_api.api.schemas import CacheInfo, Provenance
from bintu_api.errors.codes import ERROR_CODES, normalize_error_code
from bintu_api.errors.tool_errors import build_mcp_tool_error_result
from bintu_api.extraction.context import ContextResult, count_tokens, normalize_mode
from bintu_api.extraction.response import (
    build_mcp_envelope,
    build_response_provenance,
    build_rest_response,
)
from bintu_api.mcp import (
    TOOL_ANNOTATIONS,
    TOOL_DESCRIPTION,
    TOOL_INPUT_SCHEMA,
    TOOL_NAME,
    TOOL_OUTPUT_SCHEMA,
)
from bintu_api.scraper.fetcher import UpstreamHTTPError
from bintu_api.settings import Settings
from main import create_app


class McpToolMetadataContractTests(unittest.TestCase):
    """Lock the MCP tool surface: name, description, annotations, schemas."""

    def test_tool_name_is_stable(self):
        self.assertEqual(TOOL_NAME, "bintu_scrape_text")

    def test_tool_description_is_nonempty_string(self):
        self.assertIsInstance(TOOL_DESCRIPTION, str)
        self.assertGreater(len(TOOL_DESCRIPTION), 0)

    def test_tool_annotations_are_stable(self):
        self.assertEqual(
            TOOL_ANNOTATIONS,
            {
                "title": "Bintu Scrape Text",
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": True,
            },
        )

    def test_tool_input_schema_requires_url_and_is_strict(self):
        self.assertEqual(TOOL_INPUT_SCHEMA.get("required"), ["url"])
        self.assertEqual(TOOL_INPUT_SCHEMA.get("additionalProperties"), False)
        self.assertIn("url", TOOL_INPUT_SCHEMA["properties"])

    def test_tool_input_schema_has_expected_properties(self):
        expected = {
            "url",
            "render_js",
            "links",
            "footnote_url_policy",
            "max_footnote_url_length",
            "mode",
            "chunk_token_budget",
            "max_tokens",
            "cache",
            "persist",
            "sections",
        }
        self.assertEqual(set(TOOL_INPUT_SCHEMA["properties"].keys()), expected)

    def test_tool_output_schema_required_fields(self):
        required = set(TOOL_OUTPUT_SCHEMA.get("required", []))
        expected = {
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
        self.assertEqual(required, expected)

    def test_tool_output_schema_chunk_items_required(self):
        chunks = TOOL_OUTPUT_SCHEMA["properties"]["chunks"]
        self.assertEqual(
            set(chunks["items"]["required"]),
            {"index", "text", "tokens", "approx_tokens"},
        )

    def test_output_schema_is_valid_draft202012(self):
        Draft202012Validator.check_schema(TOOL_OUTPUT_SCHEMA)


class ErrorCodeTaxonomyTests(unittest.TestCase):
    """Lock the machine-readable error-code taxonomy."""

    def test_error_taxonomy_is_frozenset(self):
        self.assertIsInstance(ERROR_CODES, frozenset)

    def test_error_taxonomy_contains_core_codes(self):
        for code in (
            "upstream_rate_limited",
            "invalid_or_unsafe_url",
            "invalid_api_key",
            "burst_rate_limit_exceeded",
            "upstream_access_denied",
            "upstream_connection_error",
            "upstream_http_error",
            "upstream_timeout",
            "too_many_redirects",
            "render_js_disabled",
            "unknown_tool",
            "invalid_arguments",
        ):
            self.assertIn(code, ERROR_CODES)

    def test_all_error_codes_are_snake_case(self):
        pattern = re.compile(r"^[a-z0-9_]+$")
        for code in ERROR_CODES:
            self.assertTrue(pattern.match(code), f"not snake_case: {code!r}")
        self.assertFalse(any("__" in code for code in ERROR_CODES))


class NormalizeErrorCodeTests(unittest.TestCase):
    """Lock normalize_error_code behavior: camel/kebab/space -> snake_case."""

    def test_camel_case_to_snake(self):
        self.assertEqual(
            normalize_error_code("UpstreamRateLimited"), "upstream_rate_limited"
        )

    def test_kebab_case_to_snake(self):
        self.assertEqual(
            normalize_error_code("upstream-rate-limited"), "upstream_rate_limited"
        )

    def test_spaces_to_snake(self):
        self.assertEqual(
            normalize_error_code("upstream rate limited"), "upstream_rate_limited"
        )

    def test_whitespace_trimmed(self):
        self.assertEqual(
            normalize_error_code("  upstream_rate_limited  "),
            "upstream_rate_limited",
        )

    def test_multiple_separators_collapsed(self):
        self.assertEqual(
            normalize_error_code("upstream__rate--limited"), "upstream_rate_limited"
        )

    def test_known_code_passthrough(self):
        self.assertEqual(
            normalize_error_code("upstream_rate_limited"), "upstream_rate_limited"
        )

    def test_raises_on_none(self):
        with self.assertRaises(ValueError):
            normalize_error_code(None)

    def test_raises_on_empty_string(self):
        with self.assertRaises(ValueError):
            normalize_error_code("")

    def test_raises_on_whitespace_only(self):
        with self.assertRaises(ValueError):
            normalize_error_code("   ")


class NormalizeModeTests(unittest.TestCase):
    """Lock normalize_mode: canonical modes, case/whitespace, chunked alias."""

    def test_canonical_modes_passthrough(self):
        for mode in ("scrape", "chunk", "summarize"):
            self.assertEqual(normalize_mode(mode), mode)

    def test_case_insensitive(self):
        self.assertEqual(normalize_mode("CHUNK"), "chunk")
        self.assertEqual(normalize_mode("Scrape"), "scrape")
        self.assertEqual(normalize_mode("SUMMARIZE"), "summarize")

    def test_whitespace_tolerant(self):
        self.assertEqual(normalize_mode(" Scrape "), "scrape")
        self.assertEqual(normalize_mode("\tchunk\t"), "chunk")

    def test_chunked_alias_normalizes_to_chunk(self):
        self.assertEqual(normalize_mode("chunked"), "chunk")

    def test_unknown_mode_raises_valueerror(self):
        for bad in ("not-a-mode", "chunked!", ""):
            with self.subTest(mode=bad):
                with self.assertRaises(ValueError):
                    normalize_mode(bad)


class StreamableMcpToolErrorContractTests(unittest.TestCase):
    """Lock the streamable MCP tool-error envelope shape."""

    def setUp(self):
        self.app = create_app(
            Settings(api_key="", rapidapi_proxy_secret="")
        )
        self.client = TestClient(self.app)
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        }

    def _call_tool(self, arguments):
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
        return response.json()["result"]

    def _raise_upstream_429(self, *args, **kwargs):
        raise UpstreamHTTPError(429, "Too Many Requests")

    def test_streamable_upstream_429_returns_http_200_not_429(self):
        with patch(
            "bintu_api.api.scrape_adapter._fetch_and_extract",
            side_effect=self._raise_upstream_429,
        ):
            response = self.client.post(
                "/mcp",
                headers=self.headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": TOOL_NAME,
                        "arguments": {"url": "https://example.com"},
                    },
                },
            )
        self.assertEqual(response.status_code, 200)

    def test_streamable_upstream_429_is_error_true(self):
        with patch(
            "bintu_api.api.scrape_adapter._fetch_and_extract",
            side_effect=self._raise_upstream_429,
        ):
            result = self._call_tool({"url": "https://example.com"})
        self.assertTrue(result["isError"])

    def test_streamable_upstream_429_structured_code_is_upstream_rate_limited(self):
        with patch(
            "bintu_api.api.scrape_adapter._fetch_and_extract",
            side_effect=self._raise_upstream_429,
        ):
            result = self._call_tool({"url": "https://example.com"})
        error = result["structuredContent"]["error"]
        self.assertEqual(error["code"], "upstream_rate_limited")

    def test_streamable_upstream_429_structured_retryable_true(self):
        with patch(
            "bintu_api.api.scrape_adapter._fetch_and_extract",
            side_effect=self._raise_upstream_429,
        ):
            result = self._call_tool({"url": "https://example.com"})
        error = result["structuredContent"]["error"]
        self.assertTrue(error["retryable"])
        self.assertEqual(error["retry_with"], "retry_after_delay")

    def test_streamable_upstream_429_content_text_mentions_code(self):
        with patch(
            "bintu_api.api.scrape_adapter._fetch_and_extract",
            side_effect=self._raise_upstream_429,
        ):
            result = self._call_tool({"url": "https://example.com"})
        text = result["content"][0]["text"]
        self.assertIn("upstream_rate_limited", text)

    def test_streamable_tool_error_envelope_shape(self):
        with patch(
            "bintu_api.api.scrape_adapter._fetch_and_extract",
            side_effect=self._raise_upstream_429,
        ):
            response = self.client.post(
                "/mcp",
                headers=self.headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": TOOL_NAME,
                        "arguments": {"url": "https://example.com"},
                    },
                },
            )
        body = response.json()
        self.assertEqual(body["jsonrpc"], "2.0")
        self.assertEqual(body["id"], 1)
        result = body["result"]
        self.assertEqual(result["isError"], True)
        self.assertIn("content", result)
        self.assertIn("structuredContent", result)
        self.assertIn("error", result["structuredContent"])

    def test_build_mcp_tool_error_result_shape(self):
        from bintu_api.errors.tool_errors import ToolError

        error = ToolError(
            code="upstream_rate_limited",
            message="The target returned HTTP 429.",
            hint="Retry after the delay indicated by the upstream.",
            retryable=True,
            retry_with="retry_after_delay",
        )
        result = build_mcp_tool_error_result(error)
        self.assertEqual(result["isError"], True)
        self.assertEqual(
            result["structuredContent"]["error"]["code"], "upstream_rate_limited"
        )
        self.assertTrue(result["structuredContent"]["error"]["retryable"])
        self.assertEqual(
            result["structuredContent"]["error"]["retry_with"], "retry_after_delay"
        )
        self.assertIn("upstream_rate_limited", result["content"][0]["text"])


class ProvenanceContractTests(unittest.TestCase):
    """Lock provenance fields on ContextResult, schema, and builder."""

    def test_context_result_has_provenance_fields(self):
        fields = set(ContextResult.__dataclass_fields__.keys())
        for field in (
            "request_id",
            "fetched_at",
            "requested_url",
            "final_url",
            "content_type",
            "bytes_fetched",
            "content_sha256",
            "cache",
            "extractor_version",
        ):
            self.assertIn(field, fields)

    def test_provenance_schema_fields(self):
        fields = set(Provenance.model_fields.keys())
        for field in (
            "request_id",
            "fetched_at",
            "requested_url",
            "final_url",
            "canonical_url",
            "upstream_status",
            "redirect_count",
            "content_type",
            "bytes_fetched",
            "content_sha256",
            "cache",
            "extractor_version",
        ):
            self.assertIn(field, fields)

    def test_build_response_provenance_is_additive(self):
        context = ContextResult(
            mode="scrape",
            text="hi",
            approx_tokens=1,
            html_tokens=0,
            token_method="ceil(characters/4)",
            limiting_factor="none",
            request_id="req-1",
            fetched_at="2024-01-01T00:00:00+00:00",
            requested_url="https://example.com",
            content_type="text/html",
            bytes_fetched=100,
            content_sha256="abc",
            cache=CacheInfo(hit=False, layer="none"),
            extractor_version="v1",
        )
        provenance = build_response_provenance(context)
        self.assertEqual(provenance["request_id"], "req-1")
        self.assertEqual(provenance["fetched_at"], "2024-01-01T00:00:00+00:00")
        self.assertEqual(provenance["requested_url"], "https://example.com")
        self.assertEqual(provenance["content_type"], "text/html")
        self.assertEqual(provenance["bytes_fetched"], 100)
        self.assertEqual(provenance["content_sha256"], "abc")
        self.assertEqual(
            provenance["cache"], {"hit": False, "layer": "none", "age_seconds": None}
        )
        self.assertEqual(provenance["extractor_version"], "v1")
        self.assertNotIn("final_url", provenance)
        self.assertNotIn("canonical_url", provenance)


class CacheEconomicsContractTests(unittest.TestCase):
    """Lock cache-economics fields on ContextResult and envelopes."""

    def test_context_result_has_cache_economics_fields(self):
        fields = set(ContextResult.__dataclass_fields__.keys())
        for field in (
            "cache_hit",
            "cache_layer",
            "approx_tokens",
            "tokens_saved_estimate",
            "token_method",
            "html_tokens",
            "limiting_factor",
            "truncated",
            "split",
            "chunk_count",
            "tokens",
        ):
            self.assertIn(field, fields)

    def test_cache_layer_valid_values(self):
        for layer in ("none", "memory", "persistent"):
            context = ContextResult(
                mode="scrape",
                text="hi",
                approx_tokens=1,
                html_tokens=0,
                token_method="ceil(characters/4)",
                limiting_factor="none",
                cache_layer=layer,
            )
            self.assertEqual(context.cache_layer, layer)

    def test_tokens_is_deprecated_alias_of_approx_tokens(self):
        context = ContextResult(
            mode="scrape",
            text="hi",
            approx_tokens=7,
            html_tokens=0,
            token_method="ceil(characters/4)",
            limiting_factor="none",
            tokens=7,
        )
        self.assertEqual(context.tokens, context.approx_tokens)

    def test_count_tokens_is_ceil_characters_over_4(self):
        self.assertEqual(count_tokens(""), 0)
        self.assertEqual(count_tokens("abcd"), 1)
        self.assertEqual(count_tokens("abcde"), 2)
        self.assertEqual(count_tokens("abcdefgh"), 2)


class ResponseEnvelopeContractTests(unittest.TestCase):
    """Lock REST / MCP response-envelope contract fields."""

    def setUp(self):
        self.app = create_app(
            Settings(api_key="", rapidapi_proxy_secret="")
        )
        self.client = TestClient(self.app)
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        }

    def _call_tool(self, arguments):
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
        return response.json()["result"]

    def _base_context_kwargs(self):
        return {
            "mode": "scrape",
            "text": "Extracted readable text.",
            "approx_tokens": 7,
            "html_tokens": 50,
            "token_method": "ceil(characters/4)",
            "limiting_factor": "none",
            "chunk_count": 1,
            "cache_hit": False,
            "cache_layer": "none",
            "chunks": [
                {
                    "index": 0,
                    "text": "Extracted readable text.",
                    "approx_tokens": 7,
                    "tokens": 7,
                }
            ],
            "source_url": "https://example.com",
            "extracted_at": "2024-01-01T00:00:00+00:00",
            "tokens": 7,
            "tokens_saved_estimate": 43,
            "truncated": False,
            "split": False,
            "deduplicated_count": 0,
            "low_yield": False,
        }

    def test_mcp_envelope_contains_contract_fields(self):
        context = ContextResult(**self._base_context_kwargs())
        envelope = build_mcp_envelope(context, "https://example.com")
        expected = {
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
            "deduplicated_count",
            "low_yield",
            "truncated",
            "split",
            "chunks",
        }
        self.assertTrue(expected.issubset(set(envelope.keys())))
        self.assertEqual(envelope["mode"], "scrape")
        self.assertEqual(envelope["source_url"], "https://example.com")
        self.assertEqual(envelope["tokens"], envelope["approx_tokens"])
        self.assertEqual(envelope["token_method"], "ceil(characters/4)")
        self.assertEqual(envelope["cache_layer"], "none")

    def test_rest_response_contains_contract_fields(self):
        context = ContextResult(**self._base_context_kwargs())
        response = build_rest_response(context, "https://example.com")
        expected = {
            "url",
            "text",
            "truncated",
            "cache_hit",
            "cache_layer",
            "approx_tokens",
            "token_method",
            "tokens",
            "tokens_saved_estimate",
            "low_yield",
            "provenance",
        }
        self.assertTrue(expected.issubset(set(response.keys())))
        self.assertEqual(response["tokens"], response["approx_tokens"])
        self.assertEqual(response["token_method"], "ceil(characters/4)")

    def test_mcp_envelope_validates_against_output_schema(self):
        context = ContextResult(**self._base_context_kwargs())
        envelope = build_mcp_envelope(context, "https://example.com")
        validator = Draft202012Validator(TOOL_OUTPUT_SCHEMA)
        validator.validate(envelope)

    def test_mcp_envelope_yield_hint_only_when_low_yield(self):
        base = self._base_context_kwargs()
        envelope = build_mcp_envelope(ContextResult(**base), "https://example.com")
        self.assertNotIn("yield_hint", envelope)

        low_yield = ContextResult(
            **{
                **base,
                "low_yield": True,
                "yield_hint": "page requires JavaScript",
            }
        )
        envelope = build_mcp_envelope(low_yield, "https://example.com")
        self.assertEqual(envelope["yield_hint"], "page requires JavaScript")

    def test_mcp_streamable_envelope_fields_via_live_call(self):
        """Exercise the full streamable path to lock the live envelope fields."""
        document_html = (
            b"<html><body><main><h1>Example</h1><p>Readable content here.</p>"
            b"</main></body></html>"
        )

        class _FetchResult:
            def __init__(self, body, charset, final_url):
                self.body = body
                self.charset = charset
                self.final_url = final_url

        def _fake_fetch(*args, **kwargs):
            return _FetchResult(document_html, "utf-8", "https://example.com/")

        with patch(
            "bintu_api.api.scrape_adapter.fetch_html_document",
            new=_fake_fetch,
        ):
            result = self._call_tool({"url": "https://example.com/"})

        self.assertFalse(result["isError"])
        envelope = result["structuredContent"]
        expected = {
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
        self.assertTrue(expected.issubset(set(envelope.keys())))
        self.assertEqual(envelope["token_method"], "ceil(characters/4)")
        self.assertEqual(envelope["mode"], "scrape")
        self.assertIsInstance(envelope["chunks"], list)


if __name__ == "__main__":
    unittest.main(verbosity=2)






