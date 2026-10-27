"""Offline tests for public discovery smoke checks."""

import json
import unittest
from unittest.mock import patch

from smoke_discovery import check_discovery


class SmokeDiscoveryTests(unittest.TestCase):
    def responses(self):
        example = {
            "params": {"arguments": {"url": "https://" + "example.com/"}}
        }
        llms = (
            "bintu_scrape_text 1 MiB 6,000 cache=false skip_cache=true\\n"
            "```json\\n" + json.dumps(example) + "\\n```"
        ).replace("\\n", "\n")
        tools = {
            "jsonrpc": "2.0", "id": 901,
            "result": {"tools": [{
                "name": "bintu_scrape_text",
                "inputSchema": {"properties": {"url": {"type": "string"}}},
            }]},
        }
        return [
            (200, "text/plain", "User-agent: *\nAllow: /\n# /docs"),
            (200, "text/plain", llms),
            (200, "application/json", json.dumps(tools)),
        ]

    def test_valid_discovery_passes(self):
        with patch("smoke_discovery._fetch", side_effect=self.responses()) as fetch:
            check_discovery("https://service.invalid")
        self.assertEqual(fetch.call_count, 3)
        payload = fetch.call_args.args[1]
        self.assertEqual(payload["method"], "tools/list")

    def test_markdown_target_in_json_example_is_rejected(self):
        responses = self.responses()
        url = "https://" + "example.com/"
        status, content_type, text = responses[1]
        responses[1] = (
            status, content_type,
            text.replace(url, "[" + url + "](" + url + ")"),
        )
        with patch("smoke_discovery._fetch", side_effect=responses):
            with self.assertRaisesRegex(ValueError, "plain URL"):
                check_discovery("https://service.invalid")

    def test_json_rpc_error_is_rejected(self):
        responses = self.responses()
        responses[2] = (
            200, "application/json",
            json.dumps({
                "jsonrpc": "2.0", "id": 901,
                "error": {"code": -32603, "message": "Synthetic error"},
            }),
        )
        with patch("smoke_discovery._fetch", side_effect=responses):
            with self.assertRaisesRegex(ValueError, "JSON-RPC error"):
                check_discovery("https://service.invalid")


if __name__ == "__main__":
    unittest.main()
