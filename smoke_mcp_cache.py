"""Opt-in authenticated MCP refresh -> persistent-cache smoke check."""

import json
import urllib.request


TIMEOUT_SECONDS = 60

PRESERVED_FIELDS = (
    "mode",
    "tokens",
    "approx_tokens",
    "html_tokens",
    "token_method",
    "limiting_factor",
    "chunk_count",
    "source_url",
    "extracted_at",
    "tokens_saved_estimate",
    "truncated",
    "split",
    "chunks",
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _call(base_url, api_key, target_url, *, cache, request_id):
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {
            "name": "bintu_scrape_text",
            "arguments": {
                "url": target_url,
                "mode": "scrape",
                "render_js": False,
                "cache": cache,
            },
        },
    }

    request = urllib.request.Request(
        base_url + "/mcp",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "X-API-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=TIMEOUT_SECONDS,
    ) as response:
        _require(
            response.status == 200,
            "MCP: expected HTTP 200",
        )
        _require(
            response.headers.get_content_type() == "application/json",
            "MCP: expected application/json",
        )
        rpc = json.loads(response.read().decode("utf-8"))

    _require(
        isinstance(rpc, dict),
        "MCP: expected JSON object",
    )
    _require(
        rpc.get("jsonrpc") == "2.0",
        "MCP: invalid JSON-RPC version",
    )
    _require(
        rpc.get("id") == request_id,
        "MCP: response ID mismatch",
    )
    _require(
        "error" not in rpc,
        "MCP: JSON-RPC error",
    )

    result = rpc.get("result")
    _require(
        isinstance(result, dict),
        "MCP: missing result",
    )
    _require(
        result.get("isError") is False,
        "MCP: tool execution failed",
    )

    envelope = result.get("structuredContent")
    _require(
        isinstance(envelope, dict),
        "MCP: missing structuredContent",
    )

    content = result.get("content")
    _require(
        isinstance(content, list) and bool(content),
        "MCP: missing text content",
    )

    first = content[0]
    _require(
        isinstance(first, dict)
        and first.get("type") == "text"
        and isinstance(first.get("text"), str),
        "MCP: invalid text content",
    )
    _require(
        json.loads(first["text"]) == envelope,
        "MCP: text/structuredContent mismatch",
    )

    return envelope


def _validate_envelope(envelope):
    _require(
        isinstance(envelope, dict),
        "MCP: invalid envelope",
    )

    for field in PRESERVED_FIELDS:
        _require(
            field in envelope,
            "MCP: missing envelope field",
        )

    _require(
        envelope["mode"] == "scrape",
        "MCP: expected scrape mode",
    )
    _require(
        isinstance(envelope["extracted_at"], str)
        and bool(envelope["extracted_at"].strip()),
        "MCP: missing extraction timestamp",
    )

    chunks = envelope["chunks"]
    _require(
        isinstance(chunks, list) and bool(chunks),
        "MCP: missing chunks",
    )
    _require(
        all(
            isinstance(chunk, dict)
            and isinstance(chunk.get("text"), str)
            for chunk in chunks
        ),
        "MCP: invalid chunks",
    )
    _require(
        any(chunk["text"].strip() for chunk in chunks),
        "MCP: empty extracted text",
    )


def check_mcp_cache(base_url, api_key, target_url):
    _require(
        isinstance(api_key, str) and bool(api_key.strip()),
        "MCP cache check requires a credential",
    )

    fresh = _call(
        base_url,
        api_key,
        target_url,
        cache=False,
        request_id=902,
    )
    _validate_envelope(fresh)

    _require(
        fresh.get("cache_hit") is False
        and fresh.get("cache_layer") == "none",
        "MCP: refresh did not bypass cache reads",
    )
    print("OK  authenticated MCP refresh")

    cached = _call(
        base_url,
        api_key,
        target_url,
        cache=True,
        request_id=903,
    )
    _validate_envelope(cached)

    _require(
        cached.get("cache_hit") is True
        and cached.get("cache_layer") == "persistent",
        "MCP: expected persistent-cache hit",
    )

    for field in PRESERVED_FIELDS:
        _require(
            cached[field] == fresh[field],
            "MCP: persistent-cache fidelity mismatch",
        )

    print("OK  MCP persistent-cache fidelity")