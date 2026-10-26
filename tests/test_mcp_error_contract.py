"""MCP tool errors must be stable, in-band, and privacy-safe."""


from __future__ import annotations


import unittest
from unittest.mock import MagicMock, patch


from fastapi import HTTPException


from bintu_api.mcp import TOOL_NAME, call_tool
from bintu_api.scraper import TargetURLRejected
from bintu_api.settings import Settings



class McpErrorContractTests(unittest.IsolatedAsyncioTestCase):
    def _request(self, *, render_js_enabled: bool = True) -> MagicMock:
        request = MagicMock()
        request.state.request_id = "mcp-test-request"
        request.app.state.settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
            render_js_enabled=render_js_enabled,
        )
        request.app.state.supabase_client = MagicMock()
        request.app.state.cache = MagicMock()
        request.app.state.cache.get.return_value = None
        request.app.state.rate_limiter = MagicMock()

        # Emulate Starlette's case-insensitive header mapping: absent headers
        # return the caller-supplied default (normally an empty string).
        request.headers.get.side_effect = (
            lambda name, default=None: default if default is not None else ""
        )

        # No direct client connection in this unit-test fake; identity falls
        # back to the same "unknown" bucket used for a real disconnected request.
        request.client = None
        return request


    def _payload(
        self,
        url: str = "https://example.com/page",
        *,
        render_js: bool = False,
    ) -> MagicMock:
        payload = MagicMock()
        payload.name = TOOL_NAME
        payload.arguments = {"url": url, "render_js": render_js}
        return payload


    async def test_unsafe_url_is_in_band(self) -> None:
        request = self._request()


        with patch(
            "bintu_api.routes._fetch_and_extract",
            side_effect=TargetURLRejected("private address"),
        ):
            response = await call_tool(
                self._payload("http://127.0.0.1/"),
                request,
            )


        self.assertTrue(response["isError"])
        self.assertIn("invalid_or_unsafe_url", response["content"][0]["text"])
        self.assertNotIn("http://127.0.0.1/", response["content"][0]["text"])


    async def test_robots_block_is_in_band(self) -> None:
        request = self._request()


        with patch(
            "bintu_api.routes._fetch_and_extract",
            side_effect=HTTPException(
                status_code=403,
                detail={
                    "code": "blocked_by_robots",
                    "message": "Fetching this page is not permitted.",
                    "hint": "The site owner controls this.",
                },
            ),
        ):
            response = await call_tool(self._payload(), request)


        self.assertTrue(response["isError"])
        self.assertIn("blocked_by_robots", response["content"][0]["text"])


    async def test_robots_unreachable_is_in_band(self) -> None:
        request = self._request()


        with patch(
            "bintu_api.routes._fetch_and_extract",
            side_effect=HTTPException(
                status_code=403,
                detail={
                    "code": "robots_unreachable",
                    "message": "robots.txt could not be retrieved.",
                    "hint": "Access is denied while robots enforcement is enabled.",
                },
            ),
        ):
            response = await call_tool(self._payload(), request)


        self.assertTrue(response["isError"])
        self.assertIn("robots_unreachable", response["content"][0]["text"])


    async def test_render_disabled_is_in_band(self) -> None:
        request = self._request(render_js_enabled=False)


        with patch(
            "bintu_api.routes._fetch_and_extract",
            side_effect=AssertionError(
                "render_js_disabled must be returned before extraction"
            ),
        ):
            response = await call_tool(
                self._payload(render_js=True),
                request,
            )


        self.assertTrue(response["isError"])
        self.assertIn("render_js_disabled", response["content"][0]["text"])



if __name__ == "__main__":
    unittest.main(verbosity=2)