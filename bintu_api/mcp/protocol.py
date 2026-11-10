"""JSON-RPC protocol helpers for the Bintu MCP surface.

This module owns transport mechanics, protocol negotiation, and request validation without handling extraction or persistence.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

import socket
from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from bintu_api.mcp.schemas import (
    TOOL_ANNOTATIONS,
    TOOL_DESCRIPTION,
    TOOL_INPUT_SCHEMA,
    TOOL_NAME,
    TOOL_OUTPUT_SCHEMA,
    TOOL_TITLE,
)
from bintu_api.scraper.fetcher import (
    PayloadTooLarge,
    TooManyRedirects,
    UnsupportedContentEncoding,
    UnsupportedMediaType,
    UpstreamHTTPError,
    UpstreamRenderError,
)
from bintu_api.settings import Settings

SERVER_NAME = "bintu"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
FALLBACK_PROTOCOL_VERSION = "2025-03-26"
PUBLIC_MCP_METHODS = frozenset({"initialize", "tools/list", "ping"})
SERVER_INSTRUCTIONS = (
    "bintu_scrape_text fetches one public absolute http(s) URL and returns its "
    "readable text, sized for an LLM context window. Only HTML/XHTML pages up to "
    "1 MiB are supported; PDF, JSON, images, and pages that need JavaScript are "
    "not. Article or main content is preferred; navigation, headers, footers, ads "
    "and cookie banners are dropped; repeated story blocks are removed "
    "(deduplicated_count); links appear as 'label (url)'; code is returned in "
    "fenced blocks with indentation kept; tables are pipe-delimited.\n\n"
    "Modes: scrape (default) returns text for the selected mode and max_tokens budget; chunk splits "
    "the whole page into chunks that each fit max_tokens (headings stay with "
    "their text, table header rows repeat in continuation chunks, one indivisible "
    "unit such as a very long table row can exceed the budget); summarize returns "
    "the leading lines and whole sentences that fit max_tokens (it is not an "
    "AI-written summary). 'chunked' is accepted as an alias for chunk.\n\n"
    "Pages are read up to a 200,000-character ceiling by default "
    "(~50,000 tokens). "
    "truncated=true with limiting_factor=char_cap means that ceiling was hit; "
    "limiting_factor=token_budget means max_tokens was; none means no limit "
    "shortened the response. Token counts are approximate. tokens and approx_tokens are approximate estimates "
    "(ceil(characters / 4)), not tokenizer counts. tokens_saved_estimate is the "
    "source-HTML estimate minus the tokens delivered in this response.\n\n"
    "Results may come from a cache (cache_hit, cache_layer). Set cache=false to "
    "bypass cache reads; set persist=false to skip the persistent write. URLs with "
    "credential-like query parameters are never stored. robots.txt is honored.\n\n"
    "JavaScript rendering (render_js) works only if the operator enables it; if a "
    "call fails with render_js_disabled, retry with render_js=false.\n\n"
    "Every mode returns the unified JSON envelope "
    "{mode, tokens, approx_tokens, html_tokens, token_method, limiting_factor, "
    "chunk_count, cache_hit, cache_layer, source_url, extracted_at,    "
    "tokens_saved_estimate, truncated, split, chunks} plus optional provenance "
    "fields (request_id, fetched_at, requested_url, final_url, content_type, "
    "bytes_fetched, content_sha256, cache, extractor_version) when available.\n\n"
    "Failures return isError=true with a stable code at "
    "structuredContent.error (invalid_or_unsafe_url, upstream_access_denied, "
    "blocked_by_robots, payload_too_large, unsupported_media_type, "
    "upstream_rate_limited, upstream_http_error, upstream_timeout, "
    "upstream_connection_error, too_many_redirects, upstream_render_error, "
    "invalid_arguments) and render the same code in content[0].text. "
    "upstream_rate_limited marks retryable=true with retry_with=retry_after_delay; "
    "other errors are not retryable.\n\n"
    "This server is stateless: no MCP sessions, no subscriptions, no SSE streams; POST "
    "one JSON-RPC message per request; GET returns an empty SSE stream. "
    "Discovery (initialize, tools/list, ping) is public; tools/call requires "
    "X-API-Key or Authorization: Bearer."
)

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
AUTH_REQUIRED = -32001
MAX_MCP_BODY_BYTES = 64 * 1024
UPSTREAM_ACCESS_DENIED_STATUSES = (401, 402, 403)


def _rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


async def _read_mcp_body(request: Request) -> bytes | None:
    content_length = request.headers.get("content-length", "")
    if content_length.isdigit() and int(content_length) > MAX_MCP_BODY_BYTES:
        return None

    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_MCP_BODY_BYTES:
            return None
        body.extend(chunk)
    return bytes(body)


def _protocol_version_header(request: Request) -> str:
    """Return the client's declared protocol version for Streamable HTTP."""
    declared = request.headers.get("mcp-protocol-version", "").strip()
    return declared or FALLBACK_PROTOCOL_VERSION


def _reject_unknown_protocol_version(request_id: Any, version: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content=_rpc_error(
            request_id,
            INVALID_PARAMS,
            f"Unsupported MCP protocol version {version!r}.",
            data={"supported": list(SUPPORTED_PROTOCOL_VERSIONS)},
        ),
    )


def _accept_header_serves_json(request: Request) -> bool:
    raw = request.headers.get("accept", "")
    if not raw.strip():
        return True
    offered = [part.split(";")[0].strip().lower() for part in raw.split(",")]
    offered = [part for part in offered if part]
    return any(part in {"application/json", "*/*", "application/*"} for part in offered)


def _reject_unsupported_accept(request_id: Any) -> JSONResponse:
    return JSONResponse(
        status_code=406,
        content=_rpc_error(
            request_id,
            INVALID_REQUEST,
            "Not Acceptable: this server returns single application/json "
            "responses; the Accept header must include application/json.",
        ),
    )


def _reject_forbidden_origin() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content=_rpc_error(
            None,
            -32000,
            "Forbidden origin",
            data={"hint": "Origin must match the request scheme + host, or be omitted for non-browser clients."},
        ),
    )


async def _empty_sse_stream(request: Request) -> Response:
    if not _origin_is_allowed(request):
        return _reject_forbidden_origin()
    return Response(
        content="",
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "close"},
    )


def _origin_is_allowed(request: Request) -> bool:
    origin = request.headers.get("origin", "").strip()
    if not origin:
        return True
    host = request.headers.get("host", "").strip().lower()
    if not host:
        return False
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip().lower()
    return origin.strip().lower() == f"{scheme}://{host}"


def _failure_code_for_error(error: Exception) -> str:
    if isinstance(error, UpstreamHTTPError):
        if error.status_code == 429:
            return "upstream_rate_limited"
        if error.status_code in UPSTREAM_ACCESS_DENIED_STATUSES:
            return "upstream_access_denied"
        return "upstream_http_error"
    if isinstance(error, UnsupportedMediaType):
        return "unsupported_media_type"
    if isinstance(error, UnsupportedContentEncoding):
        return "unsupported_content_encoding"
    if isinstance(error, PayloadTooLarge):
        return "payload_too_large"
    if isinstance(error, TooManyRedirects):
        return "too_many_redirects"
    if isinstance(error, UpstreamRenderError):
        return "upstream_render_error"
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "upstream_timeout"
    return "upstream_connection_error"


def _initialize_result(settings: Settings, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    requested = params.get("protocolVersion")
    version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else LATEST_PROTOCOL_VERSION
    return _rpc_result(
        request_id,
        {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {
                "name": SERVER_NAME,
                "title": settings.service_title,
                "version": settings.service_version,
            },
            "instructions": SERVER_INSTRUCTIONS,
        },
    )


def _tools_list_result(request_id: Any) -> dict[str, Any]:
    return _rpc_result(
        request_id,
        {
            "tools": [
                {
                    "name": TOOL_NAME,
                    "title": TOOL_TITLE,
                    "description": TOOL_DESCRIPTION,
                    "inputSchema": TOOL_INPUT_SCHEMA,
                    "outputSchema": TOOL_OUTPUT_SCHEMA,
                    "annotations": TOOL_ANNOTATIONS,
                }
            ]
        },
    )





