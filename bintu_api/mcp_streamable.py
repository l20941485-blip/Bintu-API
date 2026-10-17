"""Standard MCP Streamable HTTP endpoint (JSON-RPC 2.0, stateless).

Exposes the single ``bintu_scrape_text`` tool to real MCP clients — Claude
custom connectors (web and Desktop, both account-brokered), Claude Code, and
any other Streamable HTTP client — without adding the ``mcp`` SDK dependency.
Targets protocol revision ``2025-11-25`` (also accepting ``2025-06-18`` and
``2025-03-26`` during negotiation):

- POST /mcp accepts one JSON-RPC message per request and answers with a
  single ``application/json`` response (the spec allows skipping SSE when
  the server never pushes messages).
- GET /mcp answers with an immediately-closing empty SSE stream: the endpoint
  must support GET, but this stateless server keeps no streams to resume.
  GET /sse and GET /mcp/sse are compatibility aliases for gateways that
  probe a dedicated SSE path; they return the same empty stream with the
  same auth + Origin checks.
- DELETE/PUT/PATCH /mcp return 405: no sessions exist to terminate.
- Notifications (JSON-RPC messages without an ``id``) get 202 Accepted
  with an empty body.
- ``MCP-Protocol-Version`` is enforced on every non-``initialize`` request
  (unknown versions get 400); a missing header falls back to ``2025-03-26``
  per the spec. ``Origin`` is validated against DNS rebinding (403).

Error mapping follows the spec: protocol failures (unknown method/tool,
invalid arguments, malformed payloads) use JSON-RPC error codes, while tool
execution failures (unsafe URL, rate limit, upstream errors, render_js
disabled) are returned in-band with ``isError: true`` and a readable text so
the model can self-correct — e.g. retrying with ``render_js=false``.
"""

import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from bintu_api.auth import rate_limit_identity, verify_api_access
from bintu_api.mcp import TOOL_DESCRIPTION, TOOL_INPUT_SCHEMA, TOOL_NAME, ToolArguments
from bintu_api.routes import _scrape_text
from bintu_api.settings import Settings

logger = logging.getLogger("bintu_api.mcp_streamable")

router = APIRouter(tags=["MCP"])

SERVER_NAME = "bintu"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
FALLBACK_PROTOCOL_VERSION = "2025-03-26"
SERVER_INSTRUCTIONS = (
    "Extract readable text from public web pages with bintu_scrape_text. "
    "Pass an absolute http(s) URL; the result is readable text capped at "
    "6,000 characters. JavaScript rendering is disabled unless the operator "
    "enabled it: if a call fails with render_js_disabled, retry with "
    "render_js=false."
)

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602


def _rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _tool_error(message: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": message}], "isError": True}


def _protocol_version_header(request: Request) -> str:
    """Return the client's declared protocol version for Streamable HTTP.

    The spec requires ``MCP-Protocol-Version`` on every request after
    ``initialize``; when absent we cannot know the version, so we assume the
    ``2025-03-26`` fallback exactly as the specification directs.
    """
    declared = request.headers.get("mcp-protocol-version", "").strip()
    return declared or FALLBACK_PROTOCOL_VERSION


def _reject_unknown_protocol_version(version: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "code": "unsupported_protocol_version",
                "message": (
                    f"Unsupported MCP protocol version {version!r}; "
                    f"supported versions: {', '.join(SUPPORTED_PROTOCOL_VERSIONS)}."
                ),
            }
        },
    )


def _reject_forbidden_origin() -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32000, "message": "Forbidden origin"},
        },
    )


async def _empty_sse_stream(request: Request) -> Response:
    """Shared handler for GET /mcp and its /sse aliases (stateless: empty stream)."""
    settings: Settings = request.app.state.settings
    verify_api_access(request, settings)
    if not _origin_is_allowed(request):
        return _reject_forbidden_origin()
    return Response(
        content="",
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "close"},
    )


def _origin_is_allowed(request: Request) -> bool:
    """Validate the Origin header against DNS-rebinding attacks.

    Absent Origin (non-browser clients such as Claude Code or curl) is
    allowed. When present, the origin must match the request's own scheme +
    host; anything else is rejected with 403 per the Streamable HTTP spec.
    """
    origin = request.headers.get("origin", "").strip()
    if not origin:
        return True
    host = request.headers.get("host", "").strip().lower()
    if not host:
        return False
    scheme = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip().lower()
    return origin.strip().lower() == f"{scheme}://{host}"


def _http_detail_text(detail: Any) -> str:
    """Flatten an HTTPException detail dict into readable tool-error text."""
    if isinstance(detail, dict):
        code = detail.get("code")
        message = detail.get("message")
        prefix = f"{code}: {message}" if code and message else str(message or code or detail)
        hint = detail.get("hint")
        if hint:
            return f"{prefix}. Hint: {hint}"
        return str(prefix)
    return str(detail)


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
                    "description": TOOL_DESCRIPTION,
                    "inputSchema": TOOL_INPUT_SCHEMA,
                }
            ]
        },
    )


async def _tools_call_result(
    request: Request, settings: Settings, request_id: Any, params: dict[str, Any]
) -> dict[str, Any]:
    if params.get("name") != TOOL_NAME:
        return _rpc_error(request_id, INVALID_PARAMS, f"Unknown tool: {params.get('name')}")
    try:
        arguments = ToolArguments.model_validate(params.get("arguments") or {})
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "arguments"
        return _rpc_error(request_id, INVALID_PARAMS, f"Invalid arguments: {location}: {first['msg']}")

    if arguments.render_js and not settings.render_js_enabled:
        return _rpc_result(
            request_id,
            _tool_error(
                "render_js_disabled: JavaScript rendering is disabled on this service. "
                "Hint: Retry with render_js=false for plain HTML extraction."
            ),
        )

    try:
        result = await _scrape_text(
            request,
            arguments.url,
            include_nav=False,
            include_header=False,
            include_footer=False,
            identity=rate_limit_identity(request, settings),
            render_js=arguments.render_js,
        )
    except HTTPException as error:
        logger.info("mcp_tool_error detail=%r", error.detail)
        return _rpc_result(request_id, _tool_error(_http_detail_text(error.detail)))
    return _rpc_result(
        request_id, {"content": [{"type": "text", "text": result.text}], "isError": False}
    )


@router.post("/mcp", include_in_schema=False)
async def mcp_messages(request: Request):
    settings: Settings = request.app.state.settings
    verify_api_access(request, settings)

    if not _origin_is_allowed(request):
        logger.warning("mcp_forbidden_origin origin=%r", request.headers.get("origin", ""))
        return _reject_forbidden_origin()

    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        raise HTTPException(
            status_code=415,
            detail={
                "code": "unsupported_media_type",
                "message": "MCP requests must use Content-Type: application/json.",
            },
        )

    try:
        payload = json.loads(await request.body())
    except json.JSONDecodeError:
        return JSONResponse(_rpc_error(None, PARSE_ERROR, "Parse error"))

    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("method"), str):
        request_id = payload.get("id") if isinstance(payload, dict) else None
        return JSONResponse(_rpc_error(request_id, INVALID_REQUEST, "Invalid Request"))

    request_id = payload.get("id")
    if request_id is None:
        # Notification (e.g. notifications/initialized): 202, no body.
        return Response(status_code=202)

    method = payload["method"]
    if method != "initialize":
        declared_version = _protocol_version_header(request)
        if declared_version not in SUPPORTED_PROTOCOL_VERSIONS:
            logger.info("mcp_unsupported_protocol_version version=%r", declared_version)
            return _reject_unknown_protocol_version(declared_version)

    params = payload.get("params") or {}
    if not isinstance(params, dict):
        # MCP defines object params only; arrays (by-position) are not used.
        return JSONResponse(_rpc_error(request_id, INVALID_PARAMS, "Invalid params: expected an object"))

    if method == "initialize":
        return JSONResponse(_initialize_result(settings, request_id, params))
    if method == "ping":
        return JSONResponse(_rpc_result(request_id, {}))
    if method == "tools/list":
        return JSONResponse(_tools_list_result(request_id))
    if method == "tools/call":
        return JSONResponse(await _tools_call_result(request, settings, request_id, params))
    if method.startswith("notifications/"):
        # Tolerate a client sending a notification with an id attached.
        return JSONResponse(_rpc_result(request_id, {}))
    return JSONResponse(_rpc_error(request_id, METHOD_NOT_FOUND, f"Method not found: {method}"))


@router.get("/mcp", include_in_schema=False)
async def mcp_listen(request: Request) -> Response:
    # Stateless server: no streams to resume, so answer the mandatory GET with
    # an immediately-closing empty SSE stream instead of 405.
    return await _empty_sse_stream(request)


@router.get("/sse", include_in_schema=False)
async def mcp_listen_alias(request: Request) -> Response:
    # Compatibility alias: some gateways/marketplaces (e.g. MCPize) probe a
    # dedicated GET /sse path for SSE streaming. Same empty stateless stream
    # as GET /mcp, same auth + Origin checks.
    return await _empty_sse_stream(request)


@router.get("/mcp/sse", include_in_schema=False)
async def mcp_listen_nested_alias(request: Request) -> Response:
    # Compatibility alias: some gateways append /sse to the configured Base URL
    # (e.g. Base URL .../mcp -> GET .../mcp/sse). Same empty stream as GET /mcp.
    return await _empty_sse_stream(request)


@router.api_route("/mcp", methods=["DELETE", "PUT", "PATCH"], include_in_schema=False)
async def mcp_unsupported_methods() -> Response:
    # Stateless server: no sessions to end (DELETE); PUT/PATCH are undefined.
    return Response(status_code=405, headers={"Allow": "POST, GET"})
