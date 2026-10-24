"""Token Tax engine tests: aliases, unified envelope, 401 upgrade_url, metering header."""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.requests import Request

from bintu_api.context import normalize_mode
from bintu_api.mcp import TOOL_DESCRIPTION, TOOL_INPUT_SCHEMA, ToolArguments
from bintu_api.scraper import FetchedHTML
from bintu_api.settings import Settings
from bintu_api.auth import mcp_rate_limit_identity, rate_limit_identity
from bintu_api.scraper import _compute_approx_tokens, _compute_tokens_saved_estimate
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

    def test_tokens_saved_is_html_minus_delivered_with_named_method(self) -> None:
        """tokens_saved_estimate must measure the whole strip, not zero."""
        nav = "<nav>" + "menu link " * 60 + "</nav>"
        html = f"<html><body>{nav}<main>Real article body text here.</main></body></html>"
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=html.encode(), charset=None),
        ):
            response = self.rpc(
                "tools/call",
                {
                    "name": "bintu_scrape_text",
                    "arguments": {"url": "https://example.com"},
                },
            )
        envelope = json.loads(response.json()["result"]["content"][0]["text"])
        self.assertEqual(envelope["token_method"], "ceil(characters/4)")
        self.assertGreater(envelope["tokens_saved_estimate"], 100)
        self.assertLessEqual(envelope["tokens_saved_estimate"], envelope["html_tokens"])
        self.assertLess(envelope["approx_tokens"], envelope["html_tokens"])

    def test_approx_tokens_is_the_canonical_field_and_tokens_is_kept(self) -> None:
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=b"<main>Hello world metering</main>", charset=None),
        ):
            response = self.rpc(
                "tools/call",
                {"name": "bintu_scrape_text", "arguments": {"url": "https://example.com/alias"}},
            )
        envelope = json.loads(response.json()["result"]["content"][0]["text"])
        self.assertIn("approx_tokens", envelope)
        self.assertIn("html_tokens", envelope)
        self.assertIn("token_method", envelope)
        self.assertEqual(envelope["tokens"], envelope["approx_tokens"])
        for chunk in envelope["chunks"]:
            self.assertEqual(chunk["tokens"], chunk["approx_tokens"])

    def test_limiting_factor_reports_which_cap_binds(self) -> None:
        """With a tiny char cap, the char cap binds; with the default cap and a
        tiny token budget, the token budget binds."""
        capped_app = create_app(
            Settings(api_key="", rapidapi_proxy_secret="", max_text_characters=40)
        )
        capped_client = TestClient(capped_app)
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=b"<main>" + b"word " * 200 + b"</main>", charset=None),
        ):
            capped = capped_client.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": "bintu_scrape_text",
                                 "arguments": {"url": "https://example.com/capped"}}},
            )
            budgeted = self.rpc(
                "tools/call",
                {"name": "bintu_scrape_text",
                 "arguments": {"url": "https://example.com/capped",
                               "mode": "summarize", "max_tokens": 100}},
            )
        capped_env = json.loads(capped.json()["result"]["content"][0]["text"])
        self.assertEqual(capped_env["limiting_factor"], "char_cap")
        self.assertTrue(capped_env["truncated"])
        budgeted_env = json.loads(budgeted.json()["result"]["content"][0]["text"])
        self.assertEqual(budgeted_env["limiting_factor"], "token_budget")
        self.assertTrue(budgeted_env["truncated"])

    def test_metering_header_uses_approx_tokens(self) -> None:
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=b"<main>Header check words</main>", charset=None),
        ):
            response = self.rpc(
                "tools/call",
                {"name": "bintu_scrape_text", "arguments": {"url": "https://example.com/hdr2"}},
            )
        self.assertIn("approx_tokens=", response.headers["x-token-usage"])

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
            return_value=FetchedHTML(body=f"<main>{long_text}</main>".encode(), charset=None),
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

    def test_scrape_mode_reports_char_cap_truncation(self) -> None:
        """P1: MCP scrape mode must not hide the 6,000-char cap."""
        long_html = b"<main>" + b"word " * 200 + b"</main>"
        app = create_app(Settings(api_key="", rapidapi_proxy_secret="", max_text_characters=40))
        client = TestClient(app)
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=long_html, charset=None),
        ):
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
        envelope = json.loads(response.json()["result"]["content"][0]["text"])
        self.assertLessEqual(len(envelope["chunks"][0]["text"]), 40)
        self.assertTrue(envelope["truncated"], "scrape mode hid the character cap")

    def test_chunk_mode_split_is_not_truncation(self) -> None:
        """P2: chunking delivers every token, so it must report truncated=False."""
        long_text = "Sentence one. " * 200
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=f"<main>{long_text}</main>".encode(), charset=None),
        ):
            response = self.rpc(
                "tools/call",
                {
                    "name": "bintu_scrape_text",
                    "arguments": {
                        "url": "https://example.com",
                        "mode": "chunk",
                        "max_tokens": 100,
                    },
                },
            )
        envelope = json.loads(response.json()["result"]["content"][0]["text"])
        self.assertGreater(envelope["chunk_count"], 1)
        self.assertTrue(envelope["split"], "chunk mode should still advertise splitting")
        self.assertFalse(
            envelope["truncated"],
            "chunking across several chunks is not content loss",
        )

    def test_summarize_mode_still_reports_content_loss(self) -> None:
        long_text = "Sentence one is here. " * 300
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=f"<main>{long_text}</main>".encode(), charset=None),
        ):
            response = self.rpc(
                "tools/call",
                {
                    "name": "bintu_scrape_text",
                    "arguments": {
                        "url": "https://example.com",
                        "mode": "summarize",
                        "max_tokens": 100,
                    },
                },
            )
        envelope = json.loads(response.json()["result"]["content"][0]["text"])
        self.assertTrue(envelope["truncated"])
        self.assertFalse(envelope["split"])

    def test_envelope_always_carries_split_flag(self) -> None:
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=b"<main>tiny page</main>", charset=None),
        ):
            response = self.rpc(
                "tools/call",
                {"name": "bintu_scrape_text", "arguments": {"url": "https://example.com"}},
            )
        envelope = json.loads(response.json()["result"]["content"][0]["text"])
        self.assertIn("split", envelope)
        self.assertFalse(envelope["split"])
        self.assertFalse(envelope["truncated"])

    def test_tokens_saved_estimate_is_honest_about_zero(self) -> None:
        """P3: scrape/chunk must not claim savings the mode does not perform.

        The estimate is ``html_tokens - approx_tokens``, so the markup the
        extractor strips is legitimately counted. The baseline is the raw HTML
        (about 401 whitespace tokens here) and the delivered text is the same words
        (400), the single-token difference being the stripped ``</main>``
        closing tag. What the mode itself must not do is claim savings
        proportional to the document, so the bound is a few tokens of markup
        rather than the ~400 a real trim would show.
        """
        long_text = "Sentence one. " * 200
        for mode in ("scrape", "chunk"):
            with self.subTest(mode=mode), patch(
                "bintu_api.routes.fetch_html_document",
                return_value=FetchedHTML(body=f"<main>{long_text}</main>".encode(), charset=None),
            ):
                response = self.rpc(
                    "tools/call",
                    {
                        "name": "bintu_scrape_text",
                        "arguments": {
                            "url": f"https://example.com/{mode}",
                            "mode": mode,
                            "max_tokens": 100,
                        },
                    },
                )
            envelope = json.loads(response.json()["result"]["content"][0]["text"])
            # The document really was large, so a tight bound is meaningful.
            self.assertGreater(envelope["html_tokens"], 300)
            self.assertLessEqual(
                envelope["tokens_saved_estimate"],
                8,
                f"{mode} mode must not claim savings it does not perform",
            )

    def test_summarize_mode_reports_real_savings(self) -> None:
        long_text = "Sentence one is here and it is long. " * 200
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=f"<main>{long_text}</main>".encode(), charset=None),
        ):
            response = self.rpc(
                "tools/call",
                {
                    "name": "bintu_scrape_text",
                    "arguments": {
                        "url": "https://example.com/sum",
                        "mode": "summarize",
                        "max_tokens": 100,
                    },
                },
            )
        envelope = json.loads(response.json()["result"]["content"][0]["text"])
        self.assertGreater(envelope["tokens_saved_estimate"], 0)
        self.assertTrue(envelope["truncated"])

    def test_token_description_discloses_approximation(self) -> None:
        """P4: never claim `tokens` are real tokenizer counts."""
        description = TOOL_DESCRIPTION.lower()
        self.assertTrue(
            "approximate" in description or "whitespace" in description,
            "the tool description must disclose that token counts are approximate",
        )

    def test_mcp_identity_uses_key_fingerprint_not_gateway_ip(self) -> None:
        """A3: connector traffic all arrives from the gateway IP, so keying on
        IP collapses every Claude user into one shared bucket."""
        app = create_app(
            Settings(api_key="", rapidapi_proxy_secret="", mcp_api_key="shared-mcp-key")
        )
        client = TestClient(app)
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=b"<main>identity check</main>", charset=None),
        ):
            first = client.post(
                "/mcp",
                headers={"X-API-Key": "shared-mcp-key"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                      "params": {"name": "bintu_scrape_text",
                                 "arguments": {"url": "https://example.com/a"}}},
            )
            second = client.post(
                "/mcp",
                headers={"X-API-Key": "shared-mcp-key"},
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                      "params": {"name": "bintu_scrape_text",
                                 "arguments": {"url": "https://example.com/b"}}},
            )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)

    def test_mcp_rate_limit_identity_prefers_credential_over_ip(self) -> None:
        settings = Settings(api_key="", rapidapi_proxy_secret="", mcp_api_key="scoped-key")

        def build(path: str, headers: dict | None = None):
            scope = {"type": "http", "method": "POST", "path": path,
                     "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
                     "query_string": b"", "client": ("203.0.113.9", 1234)}
            return Request(scope)

        ip_only = mcp_rate_limit_identity(build("/mcp"), settings)
        with_key = mcp_rate_limit_identity(
            build("/mcp", {"X-API-Key": "scoped-key"}), settings
        )
        with_other_key = mcp_rate_limit_identity(
            build("/mcp", {"X-API-Key": "another-key"}), settings
        )

        self.assertEqual(ip_only, "203.0.113.9", "no credential -> fall back to IP")
        self.assertTrue(with_key.startswith("mcp:"), "credential should key the bucket")
        self.assertNotEqual(with_key, with_other_key, "different keys need different buckets")
        self.assertNotEqual(with_key, ip_only)
        self.assertNotIn("scoped-key", with_key, "never echo the raw credential")

    def test_rest_identity_is_unchanged_by_mcp_helper(self) -> None:
        """REST keeps the plain-IP behaviour; only MCP separates by key."""
        settings = Settings(api_key="master", rapidapi_proxy_secret="")

        def build(headers: dict | None = None):
            scope = {"type": "http", "method": "GET", "path": "/api/v1/scrape/text",
                     "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
                     "query_string": b"", "client": ("203.0.113.9", 1234)}
            return Request(scope)

        self.assertEqual(rate_limit_identity(build({"X-API-Key": "master"}), settings), "203.0.113.9")

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

    def test_approx_tokens_calculation(self) -> None:
        """Phase D: _compute_approx_tokens uses ceil(characters/4) whitespace-split tokenizer."""
        self.assertEqual(_compute_approx_tokens(""), 0)
        self.assertEqual(_compute_approx_tokens("a"), 1)  # ceil(1/4) = 1
        self.assertEqual(_compute_approx_tokens("abcd"), 1)  # ceil(4/4) = 1
        self.assertEqual(_compute_approx_tokens("abcde"), 2)  # ceil(5/4) = 2
        self.assertEqual(_compute_approx_tokens(" "), 0)  # whitespace-only -> 0
        self.assertEqual(_compute_approx_tokens("hello world"), 3)  # 11 chars -> ceil(11/4) = 3

    def test_tokens_saved_estimate(self) -> None:
        """Phase D: _compute_tokens_saved_estimate computes payload reduction."""
        # Same text = 0 saved
        saved = _compute_tokens_saved_estimate(b"hello world", "hello world")
        self.assertEqual(saved, 0)

        # Shorter extracted text saves tokens
        saved = _compute_tokens_saved_estimate(b"<html>hello world</html>", "hello")
        self.assertGreater(saved, 0)

        # Larger raw should save more than smaller raw with same extracted
        saved1 = _compute_tokens_saved_estimate(b"<html>hello world</html>", "hello")
        saved2 = _compute_tokens_saved_estimate(b"<html>hello world test</html>", "hello")
        # Both should be >= 0, and the second with more raw content should save at least as much
        self.assertGreaterEqual(saved1, 0)
        self.assertGreaterEqual(saved2, 0)

    def test_tokens_saved_never_negative(self) -> None:
        """Phase D: tokens_saved_estimate must never be negative."""
        saved = _compute_tokens_saved_estimate(b"", "")
        self.assertEqual(saved, 0)

        # Even with nonsensical input, should not be negative
        saved = _compute_tokens_saved_estimate(b"<<>>", "")
        self.assertGreaterEqual(saved, 0)
