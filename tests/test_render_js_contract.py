"""JavaScript rendering must be explicit, gated, and consistently reported."""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from bintu_api.mcp import TOOL_NAME
from bintu_api.scraper import FetchedHTML
from bintu_api.settings import Settings
from main import create_app


class RenderJsContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.url = "https://example.com/app"
        self.document = FetchedHTML(
            final_url=self.url,
            body=(
                b"<html><body><main><h1>Rendered</h1>"
                b"<p>This page was fetched successfully.</p></main></body></html>"
            ),
            charset="utf-8",
        )

    def _client(self, *, render_js_enabled: bool = False) -> TestClient:
        app = create_app(
            Settings(
                api_key="",
                rapidapi_proxy_secret="",
                render_js_enabled=render_js_enabled,
            )
        )
        return TestClient(app)

    def _patch_plain_fetch(self):
        return patch(
            "bintu_api.routes.fetch_html_document",
            return_value=self.document,
        )

    def _patch_rendered_fetch(self):
        return patch(
            "bintu_api.routes.fetch_rendered_html_document",
            new=AsyncMock(return_value=self.document),
        )

    def _streamable_call(self, client: TestClient, arguments: dict) -> dict:
        response = client.post(
            "/mcp",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": TOOL_NAME,
                    "arguments": {"url": self.url, **arguments},
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIn("result", payload)
        return payload["result"]

    def test_plain_extraction_never_renders(self) -> None:
        client = self._client(render_js_enabled=True)

        with self._patch_plain_fetch() as plain_fetch, self._patch_rendered_fetch() as rendered_fetch:
            response = client.get(
                "/api/v1/scrape/text",
                params={"url": self.url, "render_js": "false"},
            )

        self.assertEqual(response.status_code, 200)
        plain_fetch.assert_called_once()
        rendered_fetch.assert_not_called()

    def test_enabled_render_uses_rendered_path(self) -> None:
        client = self._client(render_js_enabled=True)

        with self._patch_plain_fetch() as plain_fetch, self._patch_rendered_fetch() as rendered_fetch:
            response = client.get(
                "/api/v1/scrape/text",
                params={"url": self.url, "render_js": "true"},
            )

        self.assertEqual(response.status_code, 200)
        rendered_fetch.assert_awaited_once()
        plain_fetch.assert_not_called()

    def test_disabled_render_returns_rest_error(self) -> None:
        client = self._client(render_js_enabled=False)

        with self._patch_plain_fetch() as plain_fetch, self._patch_rendered_fetch() as rendered_fetch:
            response = client.get(
                "/api/v1/scrape/text",
                params={"url": self.url, "render_js": "true"},
            )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["detail"]["code"], "render_js_disabled")
        plain_fetch.assert_not_called()
        rendered_fetch.assert_not_called()

    def test_streamable_disabled_render_is_in_band(self) -> None:
        client = self._client(render_js_enabled=False)

        with self._patch_plain_fetch() as plain_fetch, self._patch_rendered_fetch() as rendered_fetch:
            result = self._streamable_call(
                client,
                {"render_js": True},
            )

        self.assertTrue(result["isError"])
        self.assertIn(
            "render_js_disabled",
            result["content"][0]["text"],
        )
        plain_fetch.assert_not_called()
        rendered_fetch.assert_not_called()

    def test_legacy_disabled_render_is_in_band(self) -> None:
        client = self._client(render_js_enabled=False)

        with self._patch_plain_fetch() as plain_fetch, self._patch_rendered_fetch() as rendered_fetch:
            response = client.post(
                "/mcp/tools/call",
                json={
                    "name": TOOL_NAME,
                    "arguments": {
                        "url": self.url,
                        "render_js": True,
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["isError"])
        self.assertIn(
            "render_js_disabled",
            payload["content"][0]["text"],
        )
        plain_fetch.assert_not_called()
        rendered_fetch.assert_not_called()

    def test_streamable_enabled_render_uses_rendered_path(self) -> None:
        client = self._client(render_js_enabled=True)

        with self._patch_plain_fetch() as plain_fetch, self._patch_rendered_fetch() as rendered_fetch:
            result = self._streamable_call(
                client,
                {"render_js": True},
            )

        self.assertFalse(result["isError"])
        rendered_fetch.assert_awaited_once()
        plain_fetch.assert_not_called()

    def test_legacy_enabled_render_uses_rendered_path(self) -> None:
        client = self._client(render_js_enabled=True)

        with self._patch_plain_fetch() as plain_fetch, self._patch_rendered_fetch() as rendered_fetch:
            response = client.post(
                "/mcp/tools/call",
                json={
                    "name": TOOL_NAME,
                    "arguments": {
                        "url": self.url,
                        "render_js": True,
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["isError"])
        rendered_fetch.assert_awaited_once()
        plain_fetch.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)