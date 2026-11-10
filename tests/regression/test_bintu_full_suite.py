"""Test Bintu Full Suite for Bintu.

This module owns a focused responsibility within the service and must remain isolated from unrelated transport or persistence concerns.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

import os

import pytest
import requests

BASE_URL = os.getenv("BINTU_BASE_URL", "https://bintu-api.onrender.com")
MCP_URL = os.environ.get("BINTU_MCP_URL", f"{BASE_URL}/mcp")
TOKEN = os.getenv("BINTU_TOKEN", "")
REST_API_KEY = os.getenv("BINTU_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not TOKEN,
    reason="BINTU_TOKEN is not configured; live MCP execution requires an API key.",
)


def test_health():
    response = requests.get(f"{BASE_URL}/healthz", timeout=10)
    assert response.status_code == 200
    assert response.json().get("status") == "ok"


def test_version():
    response = requests.get(f"{BASE_URL}/version", timeout=10)
    assert response.status_code in {200, 401}


@pytest.mark.skipif(
    not REST_API_KEY,
    reason="BINTU_API_KEY is not configured; REST routes require the master API key.",
)
def test_rest_scrape():
    response = requests.get(
        f"{BASE_URL}/api/v1/scrape/text",
        params={"url": "https://www.iana.org/domains/reserved"},
        headers={"X-API-Key": REST_API_KEY},
        timeout=15,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert isinstance(data.get("text"), str)
    assert isinstance(data.get("approx_tokens"), int)
    assert isinstance(data.get("truncated"), bool)


@pytest.mark.skipif(
    not REST_API_KEY,
    reason="BINTU_API_KEY is not configured; REST routes require the master API key.",
)
def test_rest_chunks():
    response = requests.post(
        f"{BASE_URL}/api/v1/scrape/chunks?max_tokens=1000",
        json={
            "url": "https://www.iana.org/domains/reserved",
            "include_nav": False,
            "include_header": False,
            "include_footer": False,
            "render_js": False,
        },
        headers={"X-API-Key": REST_API_KEY},
        timeout=15,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data.get("mode") == "chunk"
    assert isinstance(data.get("chunks"), list)


def test_mcp_discovery():
    response = requests.post(
        MCP_URL,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        timeout=15,
    )
    assert response.status_code == 200, response.text
    tools = response.json().get("result", {}).get("tools", [])
    assert any(tool.get("name") == "bintu_scrape_text" for tool in tools)


def test_mcp_execution():
    response = requests.post(
        MCP_URL,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "bintu_scrape_text",
                "arguments": {
                    "url": "https://example.com",
                    "max_tokens": 500,
                },
            },
        },
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
        timeout=15,
    )
    assert response.status_code == 200, response.text
    assert "result" in response.json()


@pytest.mark.skipif(
    not REST_API_KEY,
    reason="BINTU_API_KEY is not configured; REST routes require the master API key.",
)
def test_error_invalid_url():
    response = requests.get(
        f"{BASE_URL}/api/v1/scrape/text",
        params={"url": "htp:/invalid-url"},
        headers={"X-API-Key": REST_API_KEY},
        timeout=10,
    )
    assert response.status_code == 400
    assert response.json().get("detail", {}).get("code") == "invalid_or_unsafe_url"


def test_error_unauthorized():
    response = requests.get(
        f"{BASE_URL}/api/v1/scrape/text",
        params={"url": "https://example.com"},
        headers={"X-API-Key": "wrong_key_12345"},
        timeout=10,
    )
    assert response.status_code == 401


