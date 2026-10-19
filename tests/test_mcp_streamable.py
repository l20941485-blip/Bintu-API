"""Tests for the standard MCP Streamable HTTP endpoint (POST /mcp)."""

import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from bintu_api.mcp import TOOL_ANNOTATIONS, TOOL_INPUT_SCHEMA, TOOL_NAME, TOOL_OUTPUT_SCHEMA
from bintu_api.scraper import FetchedHTML
from bintu_api.settings import Settings
from main import create_app


class McpStreamableTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app = create_app(Settings(api_key="", rapidapi_proxy_secret=""))
        self.client = TestClient(self.app)

    def rpc(self, method: str, params: dict | None = None, request_id: int = 1):
        return self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
        )

    def test_initialize_returns_supported_protocol_and_server_info(self) -> None:
        response = self.rpc("initialize", {"protocolVersion": "2025-11-25"})

        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertEqual(result["protocolVersion"], "2025-11-25")
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["serverInfo"]["name"], "bintu")
        self.assertEqual(result["serverInfo"]["version"], "1.0.0")

    def test_initialize_accepts_older_supported_versions(self) -> None:
        response = self.rpc("initialize", {"protocolVersion": "2025-06-18"})

        self.assertEqual(response.json()["result"]["protocolVersion"], "2025-06-18")

    def test_initialize_falls_back_to_latest_for_unknown_version(self) -> None:
        response = self.rpc("initialize", {"protocolVersion": "1999-01-01"})

        self.assertEqual(response.json()["result"]["protocolVersion"], "2025-11-25")

    def test_ping_returns_empty_result(self) -> None:
        response = self.rpc("ping")

        self.assertEqual(response.json(), {"jsonrpc": "2.0", "id": 1, "result": {}})

    def test_tools_list_matches_the_legacy_schema(self) -> None:
        response = self.rpc("tools/list")

        tools = response.json()["result"]["tools"]
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], TOOL_NAME)
        self.assertEqual(tools[0]["inputSchema"], TOOL_INPUT_SCHEMA)
        self.assertEqual(tools[0]["outputSchema"], TOOL_OUTPUT_SCHEMA)
        self.assertEqual(tools[0]["annotations"], TOOL_ANNOTATIONS)
        self.assertTrue(tools[0]["annotations"]["readOnlyHint"])
        self.assertTrue(tools[0]["description"])
        self.assertIn("url", tools[0]["inputSchema"]["properties"])

    def test_notification_returns_202_with_empty_body(self) -> None:
        response = self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, b"")

    def test_tools_call_returns_text_content(self) -> None:
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=b"<main>MCP stream</main>", charset=None),
        ):
            response = self.rpc("tools/call", {"name": TOOL_NAME, "arguments": {"url": "https://example.com"}})

        self.assertEqual(response.status_code, 200)
        payload = response.json()["result"]
        envelope = json.loads(payload["content"][0]["text"])
        self.assertEqual(envelope["mode"], "scrape")
        self.assertGreater(envelope["tokens"], 0)
        self.assertEqual(envelope["chunks"][0]["text"], "MCP stream")
        self.assertFalse(payload["isError"])

    def test_tools_call_chunk_mode_returns_structured_json(self) -> None:
        long_text = "Sentence one. " * 200
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=f"<main>{long_text}</main>", charset=None),
        ):
            response = self.rpc(
                "tools/call",
                {
                    "name": TOOL_NAME,
                    "arguments": {
                        "url": "https://example.com",
                        "mode": "chunk",
                        "max_tokens": 100,
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["result"]
        self.assertFalse(payload["isError"])
        data = json.loads(payload["content"][0]["text"])
        self.assertEqual(data["mode"], "chunk")
        self.assertGreater(data["tokens"], 0)
        self.assertTrue(all("text" in c and "tokens" in c for c in data["chunks"]))
        self.assertTrue(all(c["tokens"] <= 100 for c in data["chunks"]))

    def test_tools_call_summarize_mode_truncates_to_budget(self) -> None:
        long_text = "Sentence one. " * 100
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=f"<main>{long_text}</main>", charset=None),
        ):
            response = self.rpc(
                "tools/call",
                {
                    "name": TOOL_NAME,
                    "arguments": {
                        "url": "https://example.com",
                        "mode": "summarize",
                        "max_tokens": 100,
                    },
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["result"]
        self.assertFalse(payload["isError"])
        data = json.loads(payload["content"][0]["text"])
        self.assertEqual(data["mode"], "summarize")
        self.assertLessEqual(data["tokens"], 100)

    def test_tools_call_render_js_disabled_is_in_band_tool_error(self) -> None:
        response = self.rpc(
            "tools/call",
            {"name": TOOL_NAME, "arguments": {"url": "https://example.com", "render_js": True}},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()["result"]
        self.assertTrue(payload["isError"])
        self.assertIn("render_js_disabled", payload["content"][0]["text"])

    def test_tools_call_unknown_tool_is_invalid_params(self) -> None:
        response = self.rpc("tools/call", {"name": "other", "arguments": {"url": "https://example.com"}})

        error = response.json()["error"]
        self.assertEqual(error["code"], -32602)

    def test_tools_call_missing_url_is_invalid_params(self) -> None:
        response = self.rpc("tools/call", {"name": TOOL_NAME, "arguments": {}})

        error = response.json()["error"]
        self.assertEqual(error["code"], -32602)
        self.assertIn("url", error["message"])

    def test_unsafe_url_is_in_band_tool_error(self) -> None:
        response = self.rpc("tools/call", {"name": TOOL_NAME, "arguments": {"url": "nota-url"}})

        payload = response.json()["result"]
        self.assertTrue(payload["isError"])
        self.assertIn("invalid_or_unsafe_url", payload["content"][0]["text"])

    def test_unknown_method_is_method_not_found(self) -> None:
        response = self.rpc("resources/list")

        self.assertEqual(response.json()["error"]["code"], -32601)

    def test_malformed_json_is_parse_error(self) -> None:
        response = self.client.post(
            "/mcp",
            content="{not json",
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["error"]["code"], -32700)
        self.assertIsNone(payload["id"])

    def test_non_jsonrpc_payload_is_invalid_request(self) -> None:
        response = self.client.post("/mcp", json={"hello": "world"})

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["error"]["code"], -32600)

    def test_wrong_content_type_is_invalid_request(self) -> None:
        response = self.client.post(
            "/mcp",
            content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
            headers={"Content-Type": "text/plain"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["error"]["code"], -32600)
        self.assertIsNone(payload["id"])

    def test_array_payload_is_invalid_request(self) -> None:
        response = self.client.post(
            "/mcp",
            content=json.dumps([{"jsonrpc": "2.0", "id": 1, "method": "ping"}]),
            headers={"Content-Type": "application/json"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], -32600)

    def test_discovery_methods_pass_without_key_when_configured(self) -> None:
        # initialize/tools/list/ping are the tokenless onboarding surface:
        # health checkers and Claude Web cannot send headers during setup.
        app = create_app(Settings(api_key="owner-key", rapidapi_proxy_secret=""))
        client = TestClient(app)
        for method, params in (
            ("initialize", {"protocolVersion": "2025-11-25"}),
            ("tools/list", {}),
            ("ping", {}),
        ):
            with self.subTest(method=method):
                response = client.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                )

                self.assertEqual(response.status_code, 200)

    def test_tools_call_requires_api_key_when_configured(self) -> None:
        app = create_app(Settings(api_key="owner-key", rapidapi_proxy_secret=""))
        client = TestClient(app)
        call_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": TOOL_NAME, "arguments": {"url": "https://example.com"}},
        }
        unauthorized = client.post("/mcp", json=call_payload)

        self.assertEqual(unauthorized.status_code, 401)
        payload = unauthorized.json()
        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["id"], 1)
        self.assertEqual(payload["error"]["code"], -32001)
        self.assertIn("premium subscription", payload["error"]["message"])
        self.assertEqual(payload["error"]["data"]["code"], "premium_required")
        self.assertEqual(payload["error"]["data"]["upgrade_url"], "https://mcpize.com")
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=b"<main>gated</main>", charset=None),
        ):
            authorized = client.post(
                "/mcp", json=call_payload, headers={"X-API-Key": "owner-key"}
            )
        self.assertEqual(authorized.status_code, 200)
        envelope = json.loads(authorized.json()["result"]["content"][0]["text"])
        self.assertEqual(envelope["chunks"][0]["text"], "gated")
        self.assertIn("tokens", envelope)

    def test_initialize_is_public_so_gateway_probes_pass_without_key(self) -> None:
        app = create_app(Settings(api_key="owner-key", rapidapi_proxy_secret=""))
        client = TestClient(app)
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-11-25"},
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["serverInfo"]["name"], "bintu")

    def test_execution_accepts_authorization_bearer_with_either_key(self) -> None:
        app = create_app(
            Settings(api_key="owner-key", rapidapi_proxy_secret="", mcp_api_key="claude-key")
        )
        client = TestClient(app)
        call_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": TOOL_NAME, "arguments": {"url": "https://example.com"}},
        }
        with patch(
            "bintu_api.routes.fetch_html_document",
            return_value=FetchedHTML(body=b"<main>bearer ok</main>", charset=None),
        ):
            for token in ("owner-key", "claude-key"):
                with self.subTest(token=token):
                    response = client.post(
                        "/mcp",
                        json=call_payload,
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    self.assertEqual(response.status_code, 200)
                    envelope = json.loads(response.json()["result"]["content"][0]["text"])
                    self.assertEqual(envelope["chunks"][0]["text"], "bearer ok")
                    self.assertIn("tokens", envelope)

    def test_execution_rejects_invalid_bearer_with_premium_detail(self) -> None:
        app = create_app(
            Settings(api_key="owner-key", rapidapi_proxy_secret="", mcp_api_key="claude-key")
        )
        client = TestClient(app)
        response = client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": TOOL_NAME, "arguments": {"url": "https://example.com"}},
            },
            headers={"Authorization": "Bearer wrong-token"},
        )

        self.assertEqual(response.status_code, 401)
        payload = response.json()
        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["error"]["code"], -32001)
        self.assertEqual(payload["error"]["data"]["code"], "premium_required")
        self.assertEqual(payload["error"]["data"]["upgrade_url"], "https://mcpize.com")
        self.assertIn(
            "premium subscription",
            payload["error"]["message"],
        )

    def test_get_returns_empty_sse_stream_for_stateless_server(self) -> None:
        response = self.client.get("/mcp")

        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])

    def test_sse_alias_paths_return_same_empty_stream(self) -> None:
        for path in ("/sse", "/mcp/sse"):
            with self.subTest(path=path):
                response = self.client.get(path)

                self.assertEqual(response.status_code, 200)
                self.assertIn("text/event-stream", response.headers["content-type"])

    def test_delete_and_unknown_methods_are_method_not_allowed(self) -> None:
        for method in ("DELETE", "PUT", "PATCH"):
            with self.subTest(method=method):
                response = self.client.request(method, "/mcp")
                self.assertEqual(response.status_code, 405)
                self.assertIn("POST", response.headers["allow"])

    def test_unsupported_protocol_version_is_rejected_with_400(self) -> None:
        response = self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"MCP-Protocol-Version": "1999-01-01"},
        )

        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["id"], 1)
        self.assertEqual(payload["error"]["code"], -32602)
        self.assertIn("1999-01-01", payload["error"]["message"])
        self.assertIn("2025-11-25", payload["error"]["data"]["supported"])

    def test_supported_protocol_version_header_is_accepted(self) -> None:
        response = self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"MCP-Protocol-Version": "2025-11-25"},
        )

        self.assertEqual(response.json(), {"jsonrpc": "2.0", "id": 1, "result": {}})

    def test_missing_protocol_version_falls_back_per_spec(self) -> None:
        response = self.rpc("ping")

        self.assertEqual(response.json(), {"jsonrpc": "2.0", "id": 1, "result": {}})

    def test_foreign_origin_is_rejected_with_403(self) -> None:
        response = self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Origin": "https://evil.example"},
        )

        self.assertEqual(response.status_code, 403)

    def test_legacy_helpers_still_work_alongside(self) -> None:
        response = self.client.get("/mcp/tools")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["tools"][0]["name"], TOOL_NAME)


class McpScopedApiKeyTests(unittest.TestCase):
    """MCP_API_KEY unlocks the MCP surfaces only, never REST or /metrics."""

    def setUp(self) -> None:
        self.app = create_app(
            Settings(api_key="owner-key", rapidapi_proxy_secret="", mcp_api_key="claude-key")
        )
        self.client = TestClient(self.app)

    def rpc(self, method: str, params: dict | None = None, headers: dict | None = None):
        return self.client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
            headers=headers or {},
        )

    def test_scoped_key_is_accepted_on_streamable_endpoint(self) -> None:
        response = self.rpc("tools/list", headers={"X-API-Key": "claude-key"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["tools"][0]["name"], TOOL_NAME)

    def test_scoped_key_is_accepted_on_legacy_helpers(self) -> None:
        response = self.client.get("/mcp/tools", headers={"X-API-Key": "claude-key"})

        self.assertEqual(response.status_code, 200)

    def test_scoped_key_is_rejected_on_rest_routes(self) -> None:
        response = self.client.get(
            "/api/v1/scrape/text?url=https://example.com",
            headers={"X-API-Key": "claude-key"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "invalid_api_key")

    def test_scoped_key_is_rejected_on_metrics(self) -> None:
        response = self.client.get("/metrics", headers={"X-API-Key": "claude-key"})

        self.assertEqual(response.status_code, 401)

    def test_master_key_still_works_on_mcp(self) -> None:
        response = self.rpc("tools/list", headers={"X-API-Key": "owner-key"})

        self.assertEqual(response.status_code, 200)

    def test_unknown_key_is_rejected_on_execution(self) -> None:
        # Discovery is public now, so the wrong-key contract lives on tools/call.
        response = self.rpc(
            "tools/call",
            {"name": TOOL_NAME, "arguments": {"url": "https://example.com"}},
            headers={"X-API-Key": "wrong-key"},
        )

        self.assertEqual(response.status_code, 401)
        payload = response.json()
        self.assertEqual(payload["jsonrpc"], "2.0")
        self.assertEqual(payload["error"]["code"], -32001)
        self.assertEqual(payload["error"]["data"]["code"], "premium_required")
        self.assertEqual(payload["error"]["data"]["upgrade_url"], "https://mcpize.com")
        self.assertIn("premium subscription", payload["error"]["message"])

    def test_scoped_key_can_be_the_only_configured_secret(self) -> None:
        app = create_app(Settings(api_key="", rapidapi_proxy_secret="", mcp_api_key="claude-key"))
        client = TestClient(app)

        response = client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            headers={"X-API-Key": "claude-key"},
        )

        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
