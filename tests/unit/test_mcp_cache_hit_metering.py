"""Focused tests for MCP cache-hit metering token accounting."""

import hashlib
import unittest
from unittest.mock import AsyncMock, Mock

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from bintu_api.middleware.usage import UsageMeteringMiddleware
from bintu_api.settings import Settings


class MCPCacheHitMeteringTests(unittest.TestCase):
    def _client(self, cache_hit: bool, token_usage: int):
        app = FastAPI()
        settings = Settings(
            api_key="",
            rapidapi_proxy_secret="",
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
                    "X-Token-Usage": str(token_usage),
                    "X-Mode": "scrape",
                    "X-Cache-Hit": "true" if cache_hit else "false",
                },
            )

        return TestClient(app), supabase

    def test_fresh_extraction_records_actual_tokens(self):
        client, supabase = self._client(cache_hit=False, token_usage=42)

        response = client.post(
            "/mcp",
            headers={"Authorization": "Bearer mcpize-secret"},
            json={},
        )

        self.assertEqual(response.status_code, 200)
        identity = f"mcpize:{hashlib.sha256(b'mcpize-secret').hexdigest()[:32]}"

        supabase.rpc.assert_called_once_with(
            "increment_developer_usage",
            {
                "p_rapidapi_user": identity,
                "p_gateway": "mcpize",
                "p_scrapes": 1,
                "p_tokens": 42,
                "p_mode": "scrape",
            },
        )
        supabase.rpc.return_value.execute.assert_awaited_once()

    def test_cache_hit_records_one_scrape_and_zero_tokens(self):
        client, supabase = self._client(cache_hit=True, token_usage=9)

        response = client.post(
            "/mcp",
            headers={"Authorization": "Bearer mcpize-secret"},
            json={},
        )

        self.assertEqual(response.status_code, 200)
        identity = f"mcpize:{hashlib.sha256(b'mcpize-secret').hexdigest()[:32]}"

        supabase.rpc.assert_called_once_with(
            "increment_developer_usage",
            {
                "p_rapidapi_user": identity,
                "p_gateway": "mcpize",
                "p_scrapes": 1,
                "p_tokens": 0,
                "p_mode": "scrape",
            },
        )
        supabase.rpc.return_value.execute.assert_awaited_once()

    def test_missing_identity_records_no_event(self):
        client, supabase = self._client(cache_hit=True, token_usage=9)

        response = client.post("/mcp", json={})

        self.assertEqual(response.status_code, 200)
        supabase.rpc.assert_not_called()


if __name__ == "__main__":
    unittest.main()
