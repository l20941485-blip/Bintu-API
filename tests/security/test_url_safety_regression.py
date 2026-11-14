import pytest
from fastapi.testclient import TestClient

from main import create_app


@pytest.mark.parametrize(
    "unsafe_url",
    [
        "http://127.0.0.1",
        "http://localhost",
        "http://169.254.169.254",
        "http://[::1]",
        "http://2130706433",
        "http://0177.0.0.1",
    ],
)
def test_private_and_metadata_addresses_are_rejected(unsafe_url: str) -> None:
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
            "method": "tools/call",
            "params": {
                "name": "bintu_scrape_text",
                "arguments": {"url": unsafe_url},
            },
        },
    )

    assert response.status_code in {400, 401, 403}
