import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from bintu_api.mcp import TOOL_NAME
from bintu_api.robots import RobotsDecision
from bintu_api.scraper import FetchedHTML
from bintu_api.settings import Settings
from main import create_app


LONG_URL = "https://example.com/" + ("very/long/path/" * 44) + ("x" * 13)
PAGE_URL = "https://example.com/source"
LONG_URL_HTML = (
    f'<main><p><a href="{LONG_URL}">Source</a></p></main>'.encode()
)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        "bintu_api.routes.robots_decision",
        lambda *args, **kwargs: RobotsDecision(
            allowed=True,
            reason="disabled in tests",
            checked=False,
        ),
    )
    return TestClient(
        create_app(Settings(api_key="", rapidapi_proxy_secret=""))
    )


def _mcp_call(client, transport, arguments):
    if transport == "legacy":
        return client.post(
            "/mcp/tools/call",
            json={
                "name": TOOL_NAME,
                "arguments": arguments,
            },
        )
    return client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": TOOL_NAME,
                "arguments": arguments,
            },
        },
    )


def _mcp_text(response, transport):
    payload = response.json()
    if transport == "streamable":
        payload = payload["result"]
    return json.loads(payload["content"][0]["text"])["chunks"][0]["text"]


def test_rest_openapi_exposes_footnote_policy_options(client):
    parameters = {
        parameter["name"]: parameter
        for parameter in client.get("/openapi.json").json()["paths"][
            "/api/v1/scrape/text"
        ]["get"]["parameters"]
    }

    policy_schema = parameters["footnote_url_policy"]["schema"]
    assert policy_schema["enum"] == ["full", "truncated"]
    assert policy_schema["default"] == "full"

    length_schema = parameters["max_footnote_url_length"]["schema"]
    assert length_schema["type"] == "integer"
    assert length_schema["exclusiveMinimum"] == 0
    assert length_schema["default"] == 100


def test_rest_truncated_policy_preserves_full_default_and_reduces_tokens(client):
    with patch(
        "bintu_api.routes.fetch_html_document",
        return_value=FetchedHTML(body=LONG_URL_HTML, charset="utf-8"),
    ):
        full_response = client.get(
            "/api/v1/scrape/text",
            params={
                "url": PAGE_URL,
                "links": "footnotes",
                "footnote_url_policy": "full",
                "skip_cache": "true",
            },
        )
        truncated_response = client.get(
            "/api/v1/scrape/text",
            params={
                "url": PAGE_URL,
                "links": "footnotes",
                "footnote_url_policy": "truncated",
                "max_footnote_url_length": 100,
                "skip_cache": "true",
            },
        )

    assert full_response.status_code == 200
    assert LONG_URL in full_response.json()["text"]
    assert truncated_response.status_code == 200
    truncated_text = truncated_response.json()["text"]
    assert LONG_URL not in truncated_text
    assert "…" in truncated_text
    assert (
        truncated_response.json()["approx_tokens"]
        < full_response.json()["approx_tokens"]
    )


@pytest.mark.parametrize("policy", ["invalid", "FULL", ""])
def test_rest_rejects_invalid_footnote_url_policy(client, policy):
    response = client.get(
        "/api/v1/scrape/text",
        params={
            "url": PAGE_URL,
            "footnote_url_policy": policy,
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize("length", [0, -1])
def test_rest_rejects_non_positive_footnote_url_length(client, length):
    response = client.get(
        "/api/v1/scrape/text",
        params={
            "url": PAGE_URL,
            "max_footnote_url_length": length,
        },
    )

    assert response.status_code == 422


def test_rest_footnote_options_do_not_change_inline_links(client):
    with patch(
        "bintu_api.routes.fetch_html_document",
        return_value=FetchedHTML(body=LONG_URL_HTML, charset="utf-8"),
    ):
        response = client.get(
            "/api/v1/scrape/text",
            params={
                "url": PAGE_URL,
                "links": "inline",
                "footnote_url_policy": "truncated",
                "max_footnote_url_length": 20,
                "skip_cache": "true",
            },
        )

    assert response.status_code == 200
    assert LONG_URL in response.json()["text"]
    assert "truncated URL" not in response.json()["text"]


def test_mcp_discovery_exposes_footnote_policy_options(client):
    legacy = client.get("/mcp/tools").json()["tools"][0]["inputSchema"]
    streamable = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    ).json()["result"]["tools"][0]["inputSchema"]

    for schema in (legacy, streamable):
        properties = schema["properties"]
        assert properties["footnote_url_policy"]["enum"] == [
            "full",
            "truncated",
        ]
        assert properties["footnote_url_policy"]["default"] == "full"
        assert properties["max_footnote_url_length"]["type"] == "integer"
        assert properties["max_footnote_url_length"]["minimum"] == 1
        assert properties["max_footnote_url_length"]["default"] == 100


@pytest.mark.parametrize("transport", ["legacy", "streamable"])
def test_mcp_forwards_truncated_policy_to_footnote_extractor(
    client,
    transport,
):
    with patch(
        "bintu_api.routes.fetch_html_document",
        return_value=FetchedHTML(body=LONG_URL_HTML, charset="utf-8"),
    ):
        response = _mcp_call(
            client,
            transport,
            {
                "url": PAGE_URL,
                "links": "footnotes",
                "footnote_url_policy": "truncated",
                "max_footnote_url_length": 100,
                "cache": False,
            },
        )

    assert response.status_code == 200
    text = _mcp_text(response, transport)
    assert LONG_URL not in text
    assert "…" in text


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("footnote_url_policy", "invalid"),
        ("footnote_url_policy", "FULL"),
        ("max_footnote_url_length", 0),
        ("max_footnote_url_length", -1),
    ],
)
def test_mcp_rejects_invalid_footnote_policy_arguments(client, field, value):
    response = _mcp_call(
        client,
        "legacy",
        {"url": PAGE_URL, field: value},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_tool_arguments"
