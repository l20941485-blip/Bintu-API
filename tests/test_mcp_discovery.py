def test_legacy_mcp_tools_discovery_is_public():
    from fastapi.testclient import TestClient
    from main import create_app
    from bintu_api.settings import Settings

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
    from main import create_app
    from bintu_api.settings import Settings

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
