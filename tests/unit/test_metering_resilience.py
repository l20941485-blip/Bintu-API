"""Focused metering resilience, precedence, and redaction tests."""

import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from bintu_api.metering.identity import _hash, resolve_metering_identity
from bintu_api.middleware.usage import UsageMeteringMiddleware
from bintu_api.settings import Settings


class MeteringResilienceTests(unittest.TestCase):
    def _client(self, token_usage="42", cache_hit="false"):
        app = FastAPI()
        settings = Settings(
            api_key="master-secret",
            rapidapi_proxy_secret="rapidapi-secret",
            mcp_api_key="mcpize-secret",
        )
        app.state.settings = settings

        supabase = Mock()
        supabase.rpc.return_value.execute = AsyncMock()
        app.state.supabase_client = supabase

        app.add_middleware(UsageMeteringMiddleware)

        @app.post("/mcp")
        async def mcp():
            return JSONResponse(
                {"jsonrpc": "2.0", "id": 1, "result": {}},
                headers={
                    "X-Token-Usage": token_usage,
                    "X-Mode": "scrape",
                    "X-Cache-Hit": cache_hit,
                },
            )

        return TestClient(app), supabase, settings

    def test_supabase_failure_does_not_break_successful_extraction(self):
        client, supabase, _ = self._client()

        supabase.rpc.return_value.execute = AsyncMock(
            side_effect=RuntimeError("supabase unavailable")
        )

        with self.assertLogs("bintu_api.usage", level="WARNING") as logs:
            response = client.post(
                "/mcp",
                headers={"Authorization": "Bearer mcpize-secret"},
                json={},
            )

        self.assertEqual(response.status_code, 200)
        supabase.rpc.assert_called_once()
        self.assertTrue(
            any("usage" in message.lower() for message in logs.output)
        )

    def test_malformed_token_usage_records_zero_tokens(self):
        client, supabase, _ = self._client(token_usage="not-a-number")

        response = client.post(
            "/mcp",
            headers={"Authorization": "Bearer mcpize-secret"},
            json={},
        )

        self.assertEqual(response.status_code, 200)
        call = supabase.rpc.call_args
        self.assertEqual(call.args[1]["p_tokens"], 0)
        self.assertEqual(call.args[1]["p_scrapes"], 1)

    def test_rapidapi_identity_takes_precedence(self):
        settings = Settings(
            api_key="master-secret",
            rapidapi_proxy_secret="rapidapi-secret",
            mcp_api_key="mcpize-secret",
        )

        request = Mock()
        request.headers = {
            "Authorization": "Bearer mcpize-secret",
            "X-RapidAPI-Key": "rapidapi-key",
            "X-RapidAPI-Proxy-Secret": "rapidapi-secret",
        }

        with patch(
            "bintu_api.metering.identity.has_valid_proxy_secret",
            return_value=True,
        ):
            identity, gateway = resolve_metering_identity(request, settings)

        self.assertEqual(identity, f"rapidapi:{_hash('rapidapi-key')}")
        self.assertEqual(gateway, "rapidapi")

    def test_raw_credentials_do_not_appear_in_rpc_arguments(self):
        client, supabase, _ = self._client()

        response = client.post(
            "/mcp",
            headers={"Authorization": "Bearer mcpize-secret"},
            json={},
        )

        self.assertEqual(response.status_code, 200)
        call = supabase.rpc.call_args
        serialized = repr(call)

        self.assertNotIn("mcpize-secret", serialized)
        self.assertIn(
            f"mcpize:{_hash('mcpize-secret')}",
            serialized,
        )

    def test_credential_like_query_parameter_is_not_persisted(self):
        client, supabase, _ = self._client()

        response = client.post(
            "/mcp?api_key=super-secret-query-value",
            headers={"Authorization": "Bearer mcpize-secret"},
            json={},
        )

        self.assertEqual(response.status_code, 200)
        serialized = repr(supabase.rpc.call_args)

        self.assertNotIn("super-secret-query-value", serialized)
        self.assertNotIn("api_key=super-secret-query-value", serialized)

    def test_non_billable_mcp_methods_do_not_create_events(self):
        client, supabase, _ = self._client()

        for method in ("GET", "OPTIONS"):
            response = client.request(
                method,
                "/mcp",
                headers={"Authorization": "Bearer mcpize-secret"},
            )
            self.assertIn(response.status_code, (200, 405))

        supabase.rpc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
