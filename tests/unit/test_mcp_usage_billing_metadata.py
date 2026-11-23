"""MCP metering must attach billing classification without changing RPC billing."""

from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from bintu_api.metering.service import UsageEvent
from bintu_api.middleware.usage import UsageMeteringMiddleware
from bintu_api.settings import Settings


def _client(cache_hit: bool, token_usage: int, mode: str = "scrape"):
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
                "X-Mode": mode,
                "X-Cache-Hit": "true" if cache_hit else "false",
            },
        )

    return TestClient(app), supabase


def test_fresh_mcp_event_classifies_context_tokens():
    client, _supabase = _client(cache_hit=False, token_usage=42)

    with patch(
        "bintu_api.middleware.usage.record_usage_event",
        new=AsyncMock(),
    ) as record:
        response = client.post(
            "/mcp",
            headers={"Authorization": "Bearer mcpize-secret"},
            json={},
        )

    assert response.status_code == 200
    event = record.await_args.args[1]
    assert isinstance(event, UsageEvent)
    assert event.tokens == 42
    assert event.billing is not None
    assert event.billing.billable_units == 42
    assert event.billing.unit == "context_tokens"
    assert event.billing.cache_credit_applied is False


def test_cached_mcp_event_preserves_rpc_zero_and_applies_credit():
    client, _supabase = _client(cache_hit=True, token_usage=9)

    with patch(
        "bintu_api.middleware.usage.record_usage_event",
        new=AsyncMock(),
    ) as record:
        response = client.post(
            "/mcp",
            headers={"Authorization": "Bearer mcpize-secret"},
            json={},
        )

    assert response.status_code == 200
    event = record.await_args.args[1]
    assert event.tokens == 0
    assert event.billing is not None
    assert event.billing.billable_units == 9
    assert event.billing.unit == "context_tokens"
    assert event.billing.cache_credit_applied is True


def test_chunk_mcp_event_classifies_chunk_tokens():
    client, _supabase = _client(
        cache_hit=False,
        token_usage=312,
        mode="chunk",
    )

    with patch(
        "bintu_api.middleware.usage.record_usage_event",
        new=AsyncMock(),
    ) as record:
        response = client.post(
            "/mcp",
            headers={"Authorization": "Bearer mcpize-secret"},
            json={},
        )

    assert response.status_code == 200
    event = record.await_args.args[1]
    assert event.billing is not None
    assert event.billing.billable_units == 312
    assert event.billing.unit == "chunk_tokens"
    assert event.billing.cache_credit_applied is False
