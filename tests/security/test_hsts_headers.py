from fastapi.testclient import TestClient

from main import create_app


def test_mcp_response_includes_hsts() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/mcp",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
    )

    assert response.status_code == 200
    assert response.headers["strict-transport-security"] == (
        "max-age=31536000; includeSubDomains"
    )
