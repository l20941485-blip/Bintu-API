import os

import pytest
from fastapi.testclient import TestClient

from bintu_api.mcp import TOOL_NAME
from bintu_api.settings import Settings
from main import create_app


@pytest.fixture
def client():
    application = create_app(
        Settings(
            api_key="test-rest-key",
            rapidapi_proxy_secret="",
            mcp_api_key="test-mcp-key",
        )
    )
    return TestClient(application)


def _post(client, payload):
    return client.post(
        "/mcp/tools/call",
        headers={"X-API-Key": "test-mcp-key"},
        json=payload,
    )


def test_unknown_tool_uses_error_contract(client):
    response = _post(
        client,
        {
            "name": "not_a_real_tool",
            "arguments": {"url": "https://example.com"},
        },
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "unknown_tool"
    assert detail["message"] == "Unknown MCP tool: not_a_real_tool."
    assert detail["hint"] == f"Use the supported tool: {TOOL_NAME}."


def test_invalid_arguments_uses_error_contract(client):
    response = _post(
        client,
        {
            "name": TOOL_NAME,
            "arguments": {},
        },
    )

    assert response.status_code == 400
    detail = response.json()["detail"]
    assert detail["code"] == "invalid_tool_arguments"
    assert detail["message"] == "The tool arguments are invalid."
    assert detail["hint"] == "Check the tool input schema and retry."
    assert isinstance(detail["errors"], list)
