from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from bintu_api.extraction.cache_store import CachedMarkdown
from bintu_api.settings import Settings
from main import create_app

TEST_API_KEY = "test-extractive-summary-key"


def _cached_markdown(summary_mode: str) -> CachedMarkdown:
    return CachedMarkdown(
        markdown=(
            "# Guide\n\n"
            "Bintu extracts clean Markdown for retrieval.\n\n"
            "It preserves headings and source context."
        ),
        truncated=False,
        html_tokens=50,
        tokens_saved_estimate=40,
        limiting_factor="none",
        extracted_at="2026-01-01T00:00:00+00:00",
        content_cleaning={
            "applied": True,
            "strategy": "main_content",
            "boilerplate_lines_removed": 0,
            "terminal_sections_removed": 0,
            "deduplicated_count": 0,
            "extractive_summary": {
                "applied": True,
                "mode": summary_mode,
                "requested_sentence_count": 2,
                "returned_sentence_count": 2,
                "truncated": False,
                "sentences": [],
            },
        },
    )


@pytest.fixture()
def client() -> TestClient:
    settings = Settings(
        api_key=TEST_API_KEY,
        mcp_api_key="",
        rapidapi_proxy_secret="",
        require_auth=True,
    )
    return TestClient(create_app(settings=settings))


def patch_fetch(summary_mode: str):
    document = type(
        "FetchedHTML",
        (),
        {
            "body": b"<html><body><p>Example</p></body></html>",
            "final_url": "https://example.com/",
            "charset": "utf-8",
        },
    )()

    return patch(
        "bintu_api.api.scrape_adapter._fetch_and_extract",
        new=AsyncMock(
            return_value=(
                document,
                _cached_markdown(summary_mode),
                "none",
                False,
            )
        ),
    )


def test_rest_scrape_text_forwards_summary_options(client: TestClient):
    with patch_fetch("leading") as fetch_and_extract:
        response = client.get(
            "/api/v1/scrape/text",
            params={
                "url": "https://example.com/page",
                "main_content_only": True,
                "summary_mode": "leading",
                "summary_sentence_count": 2,
            },
            headers={"X-API-Key": TEST_API_KEY},
        )

    assert response.status_code == 200, response.text
    assert fetch_and_extract.call_args.kwargs["summary_mode"] == "leading"
    assert (
        fetch_and_extract.call_args.kwargs["summary_sentence_count"] == 2
    )


def test_mobile_scrape_text_request_accepts_summary_options():
    from bintu_api.api.schemas import MobileScrapeTextRequest

    payload = MobileScrapeTextRequest(
        url="https://example.com/page",
        main_content_only=True,
        summary_mode="key_sentences",
        summary_sentence_count=2,
    )

    assert payload.summary_mode == "key_sentences"
    assert payload.summary_sentence_count == 2


def test_mcp_tool_arguments_accept_summary_options():
    from bintu_api.mcp.tools import ToolArguments

    arguments = ToolArguments(
        url="https://example.com/page",
        main_content_only=True,
        summary_mode="leading",
        summary_sentence_count=2,
    )

    assert arguments.summary_mode == "leading"
    assert arguments.summary_sentence_count == 2


def test_mcp_tool_input_schema_declares_summary_options():
    from bintu_api.mcp.schemas import TOOL_INPUT_SCHEMA

    properties: dict[str, Any] = TOOL_INPUT_SCHEMA["properties"]

    assert properties["summary_mode"]["enum"] == [
        "none",
        "leading",
        "key_sentences",
    ]
    assert properties["summary_mode"]["default"] == "none"
    assert properties["summary_sentence_count"]["minimum"] == 1
    assert properties["summary_sentence_count"]["maximum"] == 10


def test_rest_scrape_text_returns_summary_metadata(client: TestClient):
    with patch_fetch("leading"):
        response = client.get(
            "/api/v1/scrape/text",
            params={
                "url": "https://example.com/page",
                "main_content_only": True,
                "summary_mode": "leading",
                "summary_sentence_count": 2,
            },
            headers={"X-API-Key": TEST_API_KEY},
        )

    assert response.status_code == 200, response.text

    payload = response.json()
    summary = payload["content_cleaning"]["extractive_summary"]

    assert summary["applied"] is True
    assert summary["mode"] == "leading"
    assert summary["requested_sentence_count"] == 2
    assert summary["returned_sentence_count"] == 2
    assert summary["truncated"] is False
    assert summary["sentences"] == []

    assert payload["provenance"]["request_id"]
    assert payload["content_cleaning"]["applied"] is True



def test_mcp_tool_call_returns_summary_metadata(client: TestClient):
    with patch_fetch("leading"):
        response = client.post(
            "/mcp/tools/call",
            json={
                "name": "bintu_scrape_text",
                "arguments": {
                    "url": "https://example.com/page",
                    "main_content_only": True,
                    "summary_mode": "leading",
                    "summary_sentence_count": 2,
                },
            },
            headers={"X-API-Key": TEST_API_KEY},
        )

    assert response.status_code == 200, response.text

    payload = response.json()
    assert payload["isError"] is False

    envelope = payload["structuredContent"]
    summary = envelope["content_cleaning"]["extractive_summary"]

    assert summary["applied"] is True
    assert summary["mode"] == "leading"
    assert summary["requested_sentence_count"] == 2
    assert summary["returned_sentence_count"] == 2
    assert summary["truncated"] is False
    assert summary["sentences"] == []

    assert envelope["content_cleaning"]["applied"] is True
    assert envelope["request_id"]
