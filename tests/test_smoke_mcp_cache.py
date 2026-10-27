"""Offline tests for the MCP persistent-cache smoke check."""

import json
from email.message import Message
from unittest.mock import MagicMock

from smoke_mcp_cache import _call
import copy
import unittest
from unittest.mock import patch


from smoke_mcp_cache import check_mcp_cache


def envelopes():
    fresh = {
        "mode": "scrape",
        "tokens": 4,
        "approx_tokens": 4,
        "html_tokens": 10,
        "token_method": "test",
        "limiting_factor": "none",
        "chunk_count": 1,
        "source_url": "https://example.com/",
        "extracted_at": "2026-01-01T00:00:00Z",
        "tokens_saved_estimate": 6,
        "truncated": False,
        "split": False,
        "chunks": [
            {
                "index": 0,
                "text": "# Example\nText",
                "tokens": 4,
                "approx_tokens": 4,
            }
        ],
        "cache_hit": False,
        "cache_layer": "none",
    }

    cached = copy.deepcopy(fresh)
    cached.update(cache_hit=True, cache_layer="persistent")
    return fresh, cached


class SmokeMcpCacheTests(unittest.TestCase):
    def run_check(self):
        check_mcp_cache(
            "https://service.invalid",
            "offline-test-key",
            "https://example.com/",
        )

    def test_refresh_then_persistent_hit(self):
        with patch(
            "smoke_mcp_cache._call",
            side_effect=envelopes(),
        ) as call:
            self.run_check()

        self.assertEqual(call.call_count, 2)
        self.assertIs(
            call.call_args_list[0].kwargs["cache"],
            False,
        )
        self.assertIs(
            call.call_args_list[1].kwargs["cache"],
            True,
        )

    def test_memory_hit_is_not_persistence(self):
        fresh, cached = envelopes()
        cached["cache_layer"] = "memory"

        with patch(
            "smoke_mcp_cache._call",
            side_effect=[fresh, cached],
        ):
            with self.assertRaisesRegex(
                ValueError,
                "persistent-cache hit",
            ):
                self.run_check()

    def test_refresh_cache_hit_is_rejected(self):
        fresh, cached = envelopes()
        fresh.update(cache_hit=True, cache_layer="persistent")

        with patch(
            "smoke_mcp_cache._call",
            side_effect=[fresh, cached],
        ) as call:
            with self.assertRaisesRegex(ValueError, "bypass"):
                self.run_check()

        self.assertEqual(call.call_count, 1)

    def test_fidelity_changes_are_rejected(self):
        for field, value in (
            ("extracted_at", "different"),
            ("html_tokens", 11),
            ("tokens_saved_estimate", 5),
            ("chunks", [{"text": "different"}]),
        ):
            with self.subTest(field=field):
                fresh, cached = envelopes()
                cached[field] = value

                with patch(
                    "smoke_mcp_cache._call",
                    side_effect=[fresh, cached],
                ):
                    with self.assertRaisesRegex(
                        ValueError,
                        "fidelity",
                    ):
                        self.run_check()

    def test_empty_text_is_rejected(self):
        fresh, _ = envelopes()
        fresh["chunks"][0]["text"] = " "

        with patch(
            "smoke_mcp_cache._call",
            return_value=fresh,
        ):
            with self.assertRaisesRegex(ValueError, "empty"):
                self.run_check()

    def test_missing_credential_makes_no_request(self):
        with patch("smoke_mcp_cache._call") as call:
            with self.assertRaisesRegex(ValueError, "credential"):
                check_mcp_cache(
                    "https://service.invalid",
                    "",
                    "https://example.com/",
                )

        call.assert_not_called()

class SmokeMcpTransportTests(unittest.TestCase):
    def rpc_response(self):
        fresh, _ = envelopes()
        return {
            "jsonrpc": "2.0",
            "id": 902,
            "result": {
                "isError": False,
                "structuredContent": fresh,
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(fresh),
                    }
                ],
            },
        }

    def invoke(self, rpc, *, status=200, content_type="application/json"):
        headers = Message()
        headers["Content-Type"] = content_type

        response = MagicMock()
        response.status = status
        response.headers = headers
        response.read.return_value = json.dumps(rpc).encode("utf-8")

        with patch(
            "smoke_mcp_cache.urllib.request.urlopen"
        ) as urlopen:
            urlopen.return_value.__enter__.return_value = response
            result = _call(
                "https://service.invalid",
                "offline-test-key",
                "https://example.com/",
                cache=False,
                request_id=902,
            )

        return result, urlopen

    def test_request_and_valid_response(self):
        rpc = self.rpc_response()
        result, urlopen = self.invoke(rpc)

        self.assertEqual(result, rpc["result"]["structuredContent"])
        request = urlopen.call_args.args[0]
        headers = {
            key.lower(): value
            for key, value in request.header_items()
        }
        self.assertEqual(request.full_url, "https://service.invalid/mcp")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(headers["x-api-key"], "offline-test-key")
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(
            headers["accept"],
            "application/json, text/event-stream",
        )
        self.assertEqual(
            headers["mcp-protocol-version"],
            "2025-11-25",
        )
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 60)

        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["id"], 902)
        self.assertEqual(payload["method"], "tools/call")
        self.assertEqual(
            payload["params"],
            {
                "name": "bintu_scrape_text",
                "arguments": {
                    "url": "https://example.com/",
                    "mode": "scrape",
                    "render_js": False,
                    "cache": False,
                },
            },
        )

    def test_invalid_http_response_is_rejected(self):
        for status, content_type, message in (
            (202, "application/json", "HTTP 200"),
            (200, "text/event-stream", "application/json"),
        ):
            with self.subTest(status=status, content_type=content_type):
                with self.assertRaisesRegex(ValueError, message):
                    self.invoke(
                        self.rpc_response(),
                        status=status,
                        content_type=content_type,
                    )

    def test_invalid_rpc_response_is_rejected(self):
        for field, value, message in (
            ("jsonrpc", "1.0", "JSON-RPC version"),
            ("id", 999, "ID mismatch"),
            ("error", {"code": -32603}, "JSON-RPC error"),
            ("result", None, "missing result"),
        ):
            with self.subTest(field=field):
                rpc = self.rpc_response()
                rpc[field] = value
                with self.assertRaisesRegex(ValueError, message):
                    self.invoke(rpc)

    def test_tool_error_is_rejected(self):
        rpc = self.rpc_response()
        rpc["result"]["isError"] = True
        with self.assertRaisesRegex(ValueError, "execution failed"):
            self.invoke(rpc)

    def test_missing_structured_content_is_rejected(self):
        rpc = self.rpc_response()
        rpc["result"].pop("structuredContent")
        with self.assertRaisesRegex(ValueError, "structuredContent"):
            self.invoke(rpc)

    def test_missing_text_content_is_rejected(self):
        rpc = self.rpc_response()
        rpc["result"]["content"] = []
        with self.assertRaisesRegex(ValueError, "missing text content"):
            self.invoke(rpc)

    def test_content_mismatch_is_rejected(self):
        rpc = self.rpc_response()
        rpc["result"]["content"][0]["text"] = "{}"
        with self.assertRaisesRegex(ValueError, "mismatch"):
            self.invoke(rpc)

    def test_malformed_json_is_rejected(self):
        response = MagicMock()
        response.status = 200
        response.headers = Message()
        response.headers["Content-Type"] = "application/json"
        response.read.return_value = b"not-json"

        with patch(
            "smoke_mcp_cache.urllib.request.urlopen"
        ) as urlopen:
            urlopen.return_value.__enter__.return_value = response
            with self.assertRaises(json.JSONDecodeError):
                _call(
                    "https://service.invalid",
                    "offline-test-key",
                    "https://example.com/",
                    cache=False,
                    request_id=902,
                )


if __name__ == "__main__":
    unittest.main()