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
from bintu_api.scraper import (
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
    "Token-Sanitized Context Gateway: bintu_scrape_text fetches one public absolute "
    "http(s) URL (1 MiB cap, HTML/XHTML only, nav/ads/footer stripped, article/main "
    "preferred) and returns readable text or chunks. Extraction uses a "
    "200,000-character ceiling by default; a non-default operator character "
    "cap may lower that ceiling. Output is then processed according to the "
    "selected mode and max_tokens budget. Token counts are approximate. "
    "Pass an absolute http(s) URL; private IPs and non-http schemes fail with "
    "invalid_or_unsafe_url. JavaScript rendering is disabled unless the operator "
    "enabled it: if a call fails with render_js_disabled, retry with "
    "render_js=false. Use mode=chunk (alias chunked) for vector-DB-ready chunks "
    "or mode=summarize to truncate to a max_tokens budget (alias chunk_token_budget). "
    "Every mode returns the unified JSON envelope {mode, tokens, chunk_count, "
    "cache_hit, source_url, extracted_at, tokens_saved_estimate, truncated, chunks} "
    "for predictable context budgets. This server is stateless: no MCP sessions, "
    "no subscriptions, no SSE streams; POST one JSON-RPC message per request; "
    "GET returns an empty SSE stream. Discovery (initialize, tools/list, ping) is "
    "public; tools/call requires X-API-Key or Authorization: Bearer."
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
