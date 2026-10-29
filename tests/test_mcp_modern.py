"""Unit tests for modern MCP standard-header validation."""

import base64
import unittest
from copy import deepcopy

from bintu_api.mcp_modern import (
    HeaderMismatch,
    PROTOCOL_VERSION_META_KEY,
    decode_name_header,
    validate_mirrored_headers,
)


class ModernHeaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "bintu_scrape_text",
                "arguments": {"url": "https://example.com/"},
                "_meta": {
                    PROTOCOL_VERSION_META_KEY: "2026-07-28",
                },
            },
        }
        self.headers = {
            "MCP-Protocol-Version": "2026-07-28",
            "Mcp-Method": "tools/call",
            "Mcp-Name": "bintu_scrape_text",
        }

    def test_matching_headers_are_accepted(self) -> None:
        validate_mirrored_headers(self.headers, self.payload)

    def test_header_names_are_case_insensitive(self) -> None:
        headers = {
            name.swapcase(): value
            for name, value in self.headers.items()
        }
        validate_mirrored_headers(headers, self.payload)

    def test_missing_headers_are_rejected(self) -> None:
        for name in self.headers:
            with self.subTest(header=name):
                headers = dict(self.headers)
                del headers[name]
                with self.assertRaises(HeaderMismatch):
                    validate_mirrored_headers(headers, self.payload)

    def test_mismatched_values_are_rejected(self) -> None:
        replacements = {
            "MCP-Protocol-Version": "2025-11-25",
            "Mcp-Method": "TOOLS/CALL",
            "Mcp-Name": "different_tool",
        }
        for name, value in replacements.items():
            with self.subTest(header=name):
                headers = dict(self.headers)
                headers[name] = value
                with self.assertRaises(HeaderMismatch):
                    validate_mirrored_headers(headers, self.payload)

    def test_missing_or_invalid_metadata_is_rejected(self) -> None:
        for metadata in (None, [], {}, {PROTOCOL_VERSION_META_KEY: 123}):
            with self.subTest(metadata=metadata):
                payload = deepcopy(self.payload)
                payload["params"]["_meta"] = metadata
                with self.assertRaises(HeaderMismatch):
                    validate_mirrored_headers(self.headers, payload)

    def test_encoded_name_is_decoded_before_comparison(self) -> None:
        payload = deepcopy(self.payload)
        payload["params"]["name"] = "example_\u4e16\u754c"
        encoded = base64.b64encode(
            payload["params"]["name"].encode("utf-8")
        ).decode("ascii")
        headers = dict(self.headers)
        headers["Mcp-Name"] = f"=?base64?{encoded}?="
        validate_mirrored_headers(headers, payload)

    def test_resource_read_uses_uri(self) -> None:
        payload = deepcopy(self.payload)
        payload["method"] = "resources/read"
        payload["params"]["uri"] = "file:///example"
        headers = dict(self.headers)
        headers["Mcp-Method"] = "resources/read"
        headers["Mcp-Name"] = "file:///example"
        validate_mirrored_headers(headers, payload)

    def test_discovery_does_not_require_name_header(self) -> None:
        payload = deepcopy(self.payload)
        payload["method"] = "server/discover"
        headers = dict(self.headers)
        headers["Mcp-Method"] = "server/discover"
        del headers["Mcp-Name"]
        validate_mirrored_headers(headers, payload)

    def test_malformed_name_headers_are_rejected(self) -> None:
        for value in (
            "",
            " padded ",
            "line1\nline2",
            "\u4e16\u754c",
            "=?base64?***?=",
            "=?base64?/w==?=",
        ):
            with self.subTest(value=repr(value)):
                with self.assertRaises(HeaderMismatch):
                    decode_name_header(value)

    def test_error_contract(self) -> None:
        error = HeaderMismatch("Invalid routing headers.")
        self.assertEqual(error.code, -32020)
        self.assertEqual(error.status_code, 400)


if __name__ == "__main__":
    unittest.main()