"""Streamable MCP must expose the same stable tool-error contract."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from bintu_api.errors.tool_errors import ToolError
from bintu_api.mcp import TOOL_NAME
from bintu_api.scraper import (
    PayloadTooLarge,
    TargetURLRejected,
    TooManyRedirects,
    UnsupportedContentEncoding,
    UnsupportedMediaType,
    UpstreamHTTPError,
    UpstreamRenderError,
)
from bintu_api.settings import Settings
from main import create_app


class McpStreamableErrorContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(
            Settings(
                api_key="",
                rapidapi_proxy_secret="",
                render_js_enabled=False,
            )
        )
        self.client = TestClient(self.app)
        self.headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        }

    def _call(self, arguments: dict) -> dict:
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
        payload = response.json()
        self.assertIn("result", payload)
        return payload["result"]

    def _assert_error(self, result: dict, expected_code: str) -> dict:
        self.assertTrue(result["isError"])
        error = result["structuredContent"]["error"]
        self.assertEqual(error["code"], expected_code)
        self.assertTrue(error["message"])
        self.assertIsInstance(error["retryable"], bool)
        self.assertEqual(
            result["content"][0]["text"].split(":", 1)[0],
            expected_code,
        )
        if error.get("hint"):
            self.assertIn(f". Hint: {error['hint']}", result["content"][0]["text"])
        return error

    def test_invalid_arguments_are_structured(self) -> None:
        error = self._assert_error(self._call({}), "invalid_arguments")
        self.assertIn("url", error["message"])

    def test_unsafe_url_is_in_band(self) -> None:
        with patch(
            "bintu_api.api.routes.common._fetch_and_extract",
            side_effect=TargetURLRejected("private address"),
        ):
            result = self._call({"url": "http://127.0.0.1/"})

        self._assert_error(result, "invalid_or_unsafe_url")
        self.assertIn("invalid_or_unsafe_url", result["content"][0]["text"])
        self.assertNotIn("http://127.0.0.1/", result["content"][0]["text"])

    def test_robots_block_is_in_band(self) -> None:
        with patch(
            "bintu_api.api.routes.common._fetch_and_extract",
            side_effect=HTTPException(
                status_code=403,
                detail={
                    "code": "blocked_by_robots",
                    "message": "Fetching this page is not permitted.",
                    "hint": "The site owner controls this.",
                },
            ),
        ):
            result = self._call({"url": "https://example.com/private"})

        error = self._assert_error(result, "upstream_access_denied")
        self.assertEqual(error["message"], "Fetching this page is not permitted.")

    def test_robots_unreachable_is_in_band(self) -> None:
        with patch(
            "bintu_api.api.routes.common._fetch_and_extract",
            side_effect=HTTPException(
                status_code=403,
                detail={
                    "code": "robots_unreachable",
                    "message": "robots.txt could not be retrieved.",
                    "hint": "Access is denied while robots enforcement is enabled.",
                },
            ),
        ):
            result = self._call({"url": "https://example.com/page"})

        error = self._assert_error(result, "upstream_connection_error")
        self.assertTrue(error["retryable"])

    def test_render_disabled_is_in_band(self) -> None:
        result = self._call(
            {
                "url": "https://example.com/app",
                "render_js": True,
            }
        )

        error = self._assert_error(result, "render_js_disabled")
        self.assertEqual(error["retry_with"], "render_js=false")

    def test_rate_limit_is_structured_and_retryable(self) -> None:
        with patch.object(
            self.app.state.rate_limiter,
            "check",
            side_effect=HTTPException(
                status_code=429,
                detail={
                    "code": "burst_rate_limit_exceeded",
                    "message": "Limit exceeded.",
                },
                headers={"Retry-After": "30"},
            ),
        ):
            result = self._call({"url": "https://example.com/page"})

        error = self._assert_error(result, "upstream_rate_limited")
        self.assertTrue(error["retryable"])
        self.assertEqual(error["retry_with"], "retry_after_delay")

    def test_extraction_exceptions_use_stable_codes(self) -> None:
        cases = (
            (UnsupportedMediaType(), "unsupported_media_type"),
            (UnsupportedContentEncoding(), "unsupported_content_encoding"),
            (PayloadTooLarge(), "payload_too_large"),
            (TooManyRedirects(), "too_many_redirects"),
            (UpstreamHTTPError(500, "Internal Server Error"), "upstream_http_error"),
            (UpstreamHTTPError(429, "Too Many Requests"), "upstream_rate_limited"),
            (UpstreamHTTPError(403, "Forbidden"), "upstream_access_denied"),
            (TimeoutError(), "upstream_timeout"),
            (OSError("connection failed"), "upstream_connection_error"),
            (UpstreamRenderError(), "upstream_render_error"),
        )

        for exception, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with patch(
                    "bintu_api.api.routes.common._fetch_and_extract",
                    side_effect=exception,
                ):
                    result = self._call({"url": "https://example.com/page"})
                error = self._assert_error(result, expected_code)
                self.assertIn("hint", error)

    def test_http_exceptions_use_stable_codes(self) -> None:
        cases = (
            (
                HTTPException(
                    status_code=415,
                    detail={"code": "unsupported_media_type", "message": "HTML only."},
                ),
                "unsupported_media_type",
            ),
            (
                HTTPException(
                    status_code=504,
                    detail={"code": "upstream_timeout", "message": "Timed out."},
                ),
                "upstream_timeout",
            ),
            (
                HTTPException(
                    status_code=400,
                    detail={"code": "invalid_or_unsafe_url", "message": "Invalid URL."},
                ),
                "invalid_or_unsafe_url",
            ),
            (
                HTTPException(
                    status_code=502,
                    detail={
                        "code": "upstream_rate_limited",
                        "message": "The target returned HTTP 429.",
                    },
                ),
                "upstream_rate_limited",
            ),
        )

        for exception, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with patch(
                    "bintu_api.api.routes.common._fetch_and_extract",
                    side_effect=exception,
                ):
                    result = self._call({"url": "https://example.com/page"})
                self._assert_error(result, expected_code)

    def test_tool_error_dataclass_is_frozen(self) -> None:
        error = ToolError("example", "message")
        with self.assertRaises(AttributeError):
            error.code = "changed"


if __name__ == "__main__":
    unittest.main(verbosity=2)



