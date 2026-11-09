"""Test Mcp Discovery for Bintu.

This module owns a focused responsibility within the service and must remain isolated from unrelated transport or persistence concerns.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

def test_legacy_mcp_tools_discovery_is_public():
    from fastapi.testclient import TestClient

    from bintu_api.settings import Settings
    from main import create_app

    settings = Settings(
        api_key="test-master-key",
        rapidapi_proxy_secret="",
        require_auth=True,
    )
    client = TestClient(create_app(settings))

    response = client.get("/mcp/tools")

    assert response.status_code == 200
    assert "bintu_scrape_text" in response.text


def test_legacy_mcp_tool_call_requires_auth():
    from fastapi.testclient import TestClient

    from bintu_api.settings import Settings
    from main import create_app

    settings = Settings(
        api_key="test-master-key",
        rapidapi_proxy_secret="",
        require_auth=True,
    )
    client = TestClient(create_app(settings))

    response = client.post(
        "/mcp/tools/call",
        json={
            "name": "bintu_scrape_text",
            "arguments": {"url": "https://example.com"},
        },
    )

    assert response.status_code == 401


