from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from bintu_api.database import CachedMarkdown
from bintu_api.settings import Settings
from main import create_app


TEST_API_KEY = "test-mcp-key"

HTML = """
<!doctype html>
<html lang="en">
  <head><title>Alias test</title></head>
  <body><main><h1>Alias test</h1><p>Hello Bintu.</p></main></body>
</html>
"""


@pytest.fixture()
def client() -> TestClient:
    settings = Settings(
        api_key=TEST_API_KEY,
        mcp_api_key="",
        rapidapi_proxy_secret="",
        require_auth=True,
    )
    return TestClient(create_app(settings=settings))


def call_tool(client: TestClient, arguments: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        "/mcp",
        headers={"X-API-Key": TEST_API_KEY},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "bintu_scrape_text",
                "arguments": arguments,
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert "result" in payload, payload
    return payload["result"]


def envelope(result: dict[str, Any]) -> dict[str, Any]:
    assert result.get("isError") is not True, result
    return json.loads(result["content"][0]["text"])


def patch_fetch():
    document = type(
        "FetchedHTML",
        (),
        {
            "body": HTML.encode("utf-8"),
            "final_url": "https://example.com/",
            "charset": "utf-8",
        },
    )()

    cached = CachedMarkdown(
        markdown="# Alias test\n\nHello Bintu.",
        truncated=False,
        html_tokens=50,
        tokens_saved_estimate=40,
        limiting_factor="none",
        extracted_at="2026-10-30T00:00:00+00:00",
    )

    return patch(
        "bintu_api.routes._fetch_and_extract",
        new=AsyncMock(return_value=(document, cached, "persistent")),
    )



def test_chunked_mode_alias_is_accepted(client: TestClient):
    with patch_fetch():
        result = call_tool(
            client,
            {
                "url": "https://example.com",
                "mode": "chunked",
                "chunk_token_budget": 200,
            },
        )

    data = envelope(result)
    assert data["mode"] == "chunk"


def test_chunk_token_budget_alias_is_accepted(client: TestClient):
    with patch_fetch():
        result = call_tool(
            client,
            {
                "url": "https://example.com",
                "mode": "chunk",
                "chunk_token_budget": 200,
            },
        )

    data = envelope(result)
    assert data["mode"] == "chunk"
    assert data["approx_tokens"] >= 0


def test_canonical_max_tokens_wins_over_alias(client: TestClient):
    with patch_fetch():
        result = call_tool(
            client,
            {
                "url": "https://example.com",
                "mode": "chunked",
                "chunk_token_budget": 200,
                "max_tokens": 500,
            },
        )

    data = envelope(result)
    assert data["mode"] == "chunk"


def test_input_schema_advertises_chunked_alias():
    from bintu_api.mcp import TOOL_INPUT_SCHEMA

    mode = TOOL_INPUT_SCHEMA["properties"]["mode"]

    assert mode["enum"] == [
        "scrape",
        "chunk",
        "summarize",
        "chunked",
    ]
    assert "chunk_token_budget" in TOOL_INPUT_SCHEMA["properties"]
