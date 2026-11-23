"""Contract tests preserving the existing REST and MCP response envelope."""

import json
from dataclasses import replace

from bintu_api.extraction.context import ContextResult
from bintu_api.extraction.response import (
    build_mcp_envelope,
    build_mcp_text_payload,
    build_rest_response,
)

URL = "https://example.com"


def _context() -> ContextResult:
    return ContextResult(
        mode="full",
        text="Readable example content.",
        truncated=False,
        cache_hit=False,
        cache_layer="none",
        revalidated=False,
        approx_tokens=10,
        token_method="approx",
        tokens=10,
        tokens_saved_estimate=0,
        html_tokens=10,
        limiting_factor="none",
        low_yield=False,
        source_url=URL,
        requested_url=URL,
        extracted_at="2026-01-01T00:00:00+00:00",
    )


def test_rest_response_preserves_core_envelope():
    response = build_rest_response(_context(), URL)

    assert response["url"] == URL
    assert response["text"] == "Readable example content."
    assert response["truncated"] is False
    assert response["cache_hit"] is False
    assert response["cache_layer"] == "none"
    assert response["revalidated"] is False
    assert response["approx_tokens"] == 10
    assert response["token_method"] == "approx"
    assert response["tokens"] == 10
    assert response["tokens_saved_estimate"] == 0
    assert response["low_yield"] is False
    assert response["provenance"]["requested_url"] == URL


def test_mcp_envelope_preserves_core_envelope():
    envelope = build_mcp_envelope(_context(), URL)

    assert envelope["mode"] == "full"
    assert envelope["text"] == "Readable example content."
    assert envelope["source_url"] == URL
    assert envelope["extracted_at"] == "2026-01-01T00:00:00+00:00"
    assert envelope["cache_hit"] is False
    assert envelope["cache_layer"] == "none"
    assert envelope["revalidated"] is False
    assert envelope["approx_tokens"] == 10
    assert envelope["token_method"] == "approx"
    assert envelope["tokens"] == 10
    assert envelope["requested_url"] == URL


def test_mcp_chunk_mode_preserves_chunk_only_content():
    context = replace(
        _context(),
        mode="chunk",
        chunks=[{"index": 0, "text": "Readable example content."}],
    )

    envelope = build_mcp_envelope(context, URL)

    assert envelope["text"] == ""
    assert envelope["chunks"] == [{"index": 0, "text": "Readable example content."}]


def test_mcp_serialized_payload_is_deterministic():
    envelope = build_mcp_envelope(_context(), URL)

    assert build_mcp_text_payload(envelope) == json.dumps(envelope)
    assert build_mcp_text_payload(envelope) == build_mcp_text_payload(envelope)
