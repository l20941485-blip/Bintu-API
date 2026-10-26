"""Streamable MCP transport must be safe, stateless, and standards-aligned."""

from __future__ import annotations

import unittest

from fastapi.testclient import TestClient

from bintu_api.settings import Settings
from main import create_app


class McpStreamableTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(
            Settings(
                api_key="",
                rapidapi_proxy_secret="",
                render_js_enabled=False,
            )
        )
        self.client = TestClient(self.app)
        self.json_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        }

    def _rpc(self, method: str, params: dict | None = None, request_id: int = 1) -> dict:
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            message["params"] = params
        return message

    def test_initialize_negotiates_supported_protocol(self) -> None:
        response = self.client.post(
            "/mcp",
            headers=self.json_headers,
            json=self._rpc(
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(payload["result"]["serverInfo"]["name"], "bintu")

    def test_initialize_rejects_unsupported_protocol(self) -> None:
        response = self.client.post(
            "/mcp",
            headers=self.json_headers,
            json=self._rpc(
                "initialize",
                {
                    "protocolVersion": "1999-01-01",
                    "capabilities": {},
                    "clientInfo": {"name": "test-client", "version": "1.0"},
                },
            ),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["result"]["protocolVersion"],
            "2025-11-25",
        )

    def test_tools_list_is_public(self) -> None:
        response = self.client.post(
            "/mcp",
            headers=self.json_headers,
            json=self._rpc("tools/list"),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload["result"]["tools"][0]["name"],
            "bintu_scrape_text",
        )

    def test_ping_is_public(self) -> None:
        response = self.client.post(
            "/mcp",
            headers=self.json_headers,
            json=self._rpc("ping"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"], {})

    def test_malformed_json_returns_parse_error(self) -> None:
        response = self.client.post(
            "/mcp",
            headers=self.json_headers,
            content=b"{not-json",
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], -32700)
        self.assertIsNone(payload["id"])

    def test_wrong_content_type_returns_invalid_request(self) -> None:
        response = self.client.post(
            "/mcp",
            headers={
                "Content-Type": "text/plain",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
            content=b"{}",
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], -32600)

    def test_json_only_accept_is_required(self) -> None:
        response = self.client.post(
            "/mcp",
            headers={
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
            json=self._rpc("tools/list"),
        )

        self.assertEqual(response.status_code, 406)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], -32600)

    def test_unknown_protocol_version_is_rejected(self) -> None:
        response = self.client.post(
            "/mcp",
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "1999-01-01",
            },
            json=self._rpc("tools/list"),
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], -32602)
        self.assertEqual(
            payload["error"]["data"]["supported"],
            ["2025-11-25", "2025-06-18", "2025-03-26"],
        )

    def test_notification_returns_202(self) -> None:
        response = self.client.post(
            "/mcp",
            headers=self.json_headers,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, b"")

    def test_cross_origin_request_is_forbidden(self) -> None:
        response = self.client.post(
            "/mcp",
            headers={
                **self.json_headers,
                "Origin": "https://evil.example",
                "Host": "testserver",
            },
            json=self._rpc("tools/list"),
        )

        self.assertEqual(response.status_code, 403)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], -32000)

    def test_same_origin_request_is_allowed(self) -> None:
        response = self.client.post(
            "/mcp",
            headers={
                **self.json_headers,
                "Origin": "http://testserver",
                "Host": "testserver",
            },
            json=self._rpc("tools/list"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("result", response.json())

    def test_get_returns_empty_sse_stream(self) -> None:
        response = self.client.get("/mcp")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"].split(";")[0], "text/event-stream")
        self.assertEqual(response.content, b"")

    def test_delete_is_method_not_allowed(self) -> None:
        response = self.client.delete("/mcp")

        self.assertEqual(response.status_code, 405)
        self.assertIn("POST", response.headers["Allow"])

    def test_unknown_method_returns_method_not_found(self) -> None:
        response = self.client.post(
            "/mcp",
            headers=self.json_headers,
            json=self._rpc("resources/list"),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["error"]["code"], -32601)


if __name__ == "__main__":
    unittest.main(verbosity=2)