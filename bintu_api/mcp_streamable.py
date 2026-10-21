"""Standard MCP Streamable HTTP endpoint (JSON-RPC 2.0, stateless).

Exposes the single ``bintu_scrape_text`` tool to real MCP clients — Claude
custom connectors (web and Desktop, both account-brokered), Claude Code, and
any other Streamable HTTP client — without adding the ``mcp`` SDK dependency.
Targets protocol revision ``2025-11-25`` (also accepting ``2025-06-18`` and
``2025-03-26`` during negotiation):

- POST /mcp accepts one JSON-RPC message per request and answers with a
  single ``application/json`` response (the spec allows skipping SSE when
  the server never pushes messages). ``initialize``, ``tools/list`` and
  ``ping`` are public discovery/onboarding methods (protocol negotiation,
  tool schemas, liveness — never extraction); every other method — above
  all ``tools/call`` — requires the master API_KEY, the scoped
  MCP_API_KEY, or ``Authorization: Bearer`` with either key, so gateway
  health-checkers and marketplace audits that omit the upstream token
  complete instantly while all billable work stays behind auth (401 with
  a premium-subscription detail).
- GET /mcp answers with an immediately-closing empty SSE stream: the endpoint
  must support GET, but this stateless server keeps no streams to resume.
  GET /sse and GET /mcp/sse are compatibility aliases for gateways that
  probe a dedicated SSE path; they return the same public empty stream with
  Origin checks only (no extraction ever happens on GET).
- DELETE/PUT/PATCH /mcp return 405: no sessions exist to terminate
  (stateless by design; documented in initialize instructions).
- Transport failures (malformed JSON, non-JSON-RPC payloads, wrong
  content-type, unknown MCP-Protocol-Version) answer HTTP 400 with the
  standard {"jsonrpc": "2.0", "id", "error": {"code", "message", "data"}}
  envelope; auth failures on billable methods answer HTTP 401 with code
  -32001 in the same envelope.
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

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from bintu_api.auth import (
    mcp_rate_limit_identity,
    mcp_upgrade_url,
    verify_mcp_execution_access,
)
from bintu_api.context import extract_context, normalize_mode
from bintu_api.database import DATABASE_TIMEOUT_SECONDS, increment_token_usage
from bintu_api.mcp import TOOL_ANNOTATIONS, TOOL_DESCRIPTION, TOOL_INPUT_SCHEMA, TOOL_NAME, TOOL_OUTPUT_SCHEMA, TOOL_TITLE, ToolArguments
from bintu_api.settings import Settings

logger = logging.getLogger("bintu_api.mcp_streamable")

router = APIRouter(tags=["MCP"])

SERVER_NAME = "bintu"
SUPPORTED_PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
LATEST_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[0]
FALLBACK_PROTOCOL_VERSION = "2025-03-26"
# Methods that pass without credentials: capability handshake, tool
# discovery, and liveness. None of them extract anything, so gateway
# health-checkers and marketplace audits (which cannot send headers during
# onboarding) complete instantly while tools/call and every other method
# stay behind verify_mcp_execution_access.
PUBLIC_MCP_METHODS = frozenset({"initialize", "tools/list", "ping"})
SERVER_INSTRUCTIONS = (
    "Token-Sanitized Context Gateway: bintu_scrape_text fetches one public absolute "
    "http(s) URL (1 MiB cap, HTML/XHTML only, nav/ads/footer stripped, article/main "
    "preferred) and returns readable text capped at 6,000 characters. "
    "Pass an absolute http(s) URL; private IPs and non-http schemes fail with "
    "invalid_or_unsafe_url. JavaScript rendering is disabled unless the operator "
    "enabled it: if a call fails with render_js_disabled, retry with "
    "render_js=false. Use mode=chunk (alias chunked) for vector-DB-ready chunks "
    "or mode=summarize to truncate to a max_tokens budget (alias chunk_token_budget). "
    "Every mode returns the unified JSON envelope {mode, tokens, chunk_count, "
    "cache_hit, source_url, extracted_at, tokens_saved_estimate, truncated, chunks} "
    "for predictable context budgets. This server is stateless: no MCP sessions, "
    "no subscriptions, no SSE streams — POST one JSON-RPC message per request; "
    "GET returns an empty SSE stream. Discovery (initialize, tools/list, ping) is "
    "public; tools/call requires X-API-Key or Authorization: Bearer."
)

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
# Custom server error: authentication required for billable MCP execution.
# Stays inside the JSON-RPC reserved range (-32000..-32099) so strict
# validators still recognise the envelope.
AUTH_REQUIRED = -32001


def _rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _rpc_error(
    request_id: Any, code: int, message: str, data: Any = None
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


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


def _reject_unknown_protocol_version(request_id: Any, version: str) -> JSONResponse:
    # Strict scanners expect the standard JSON-RPC envelope even for
    # transport-level rejections — never a bare {"error": ...} shape.
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
    """True unless the client explicitly refuses application/json responses.

    The transport requires clients to send ``Accept: application/json,
    text/event-stream``. This server answers every POST with a single JSON
    response and never opens an SSE stream, so a client that lists other
    media types but not JSON cannot be served (HTTP 406). Clients that send
    no Accept header at all (gateway Test buttons, curl) are tolerated —
    rejecting the largest installed base would be worse than the
    corner-case protocol violation.
    """
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
    """Shared handler for GET /mcp and its /sse aliases (stateless: empty stream).

    GET is the tokenless liveness surface: gateway health-checkers and
    marketplace audits probe it without credentials, and no extraction ever
    happens here, so auth is intentionally skipped (POST tools/call stays
    gated). Origin is still validated against DNS rebinding.
    """
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
        upgrade_url = detail.get("upgrade_url")
        if upgrade_url:
            return f"{prefix}. Subscribe: {upgrade_url}"
        return str(prefix)
    return str(detail)


def _metering_identity(request: Request, settings: Settings) -> str:
    """Identity for token metering: RapidAPI subscriber, MCP key, or IP.

    Reuses the same bucket as rate limiting: a keyed caller is metered under
    its key fingerprint (without the raw secret), not under the gateway's IP.
    """
    identity = mcp_rate_limit_identity(request, settings)
    if identity.startswith("rapidapi:"):
        return identity.split("rapidapi:", 1)[1]
    if identity.startswith("mcp:"):
        return identity
    return f"mcp:{identity}"


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


async def _tools_call_result(
    request: Request, settings: Settings, request_id: Any, params: dict[str, Any]
) -> dict[str, Any]:
    if params.get("name") != TOOL_NAME:
        return _rpc_error(request_id, INVALID_PARAMS, f"Unknown tool: {params.get('name')}")
    raw_arguments = params.get("arguments") or {}
    if isinstance(raw_arguments, dict):
        # Canonicalize pitch-name aliases BEFORE Pydantic validation so raw
        # JSON-RPC calls benefit too; canonical max_tokens wins on conflict.
        raw_arguments = dict(raw_arguments)
        if "mode" in raw_arguments:
            try:
                raw_arguments["mode"] = normalize_mode(raw_arguments["mode"])
            except ValueError as error:
                return _rpc_error(request_id, INVALID_PARAMS, f"Invalid arguments: mode: {error}")
        if "chunk_token_budget" in raw_arguments:
            if "max_tokens" in raw_arguments:
                logger.warning(
                    "mcp_alias_conflict canonical=max_tokens wins over chunk_token_budget"
                )
                raw_arguments.pop("chunk_token_budget")
            else:
                raw_arguments["max_tokens"] = raw_arguments.pop("chunk_token_budget")
    try:
        arguments = ToolArguments.model_validate(raw_arguments)
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
        context = await extract_context(
            request,
            arguments.url,
            mode=arguments.mode,
            max_tokens=arguments.max_tokens,
            cache=arguments.cache,
            render_js=arguments.render_js,
            include_nav=False,
            include_header=False,
            include_footer=False,
            identity=mcp_rate_limit_identity(request, settings),
            settings=settings,
        )
    except HTTPException as error:
        logger.info("mcp_tool_error detail=%r", error.detail)
        return _rpc_result(request_id, _tool_error(_http_detail_text(error.detail)))
    except ValueError as error:
        logger.info("mcp_tool_error value_error=%r", error)
        return _rpc_error(request_id, INVALID_PARAMS, f"Invalid arguments: {error}")

    # Unified Token Tax envelope in content[0].text across ALL modes for
    # predictable context budgets (no tier caps in code; dashboards own quota).
    # `tokens` is a deprecated alias of `approx_tokens` (kept for one release);
    # `token_method` names the counter; `html_tokens` is the fetched-document
    # baseline for `tokens_saved_estimate`; `limiting_factor` says which cap bound.
    envelope = {
        "mode": context.mode,
        "tokens": context.tokens,
        "approx_tokens": context.approx_tokens,
        "html_tokens": context.html_tokens,
        "token_method": context.token_method,
        "limiting_factor": context.limiting_factor,
        "chunk_count": context.chunk_count,
        "cache_hit": context.cache_hit,
        "source_url": context.source_url,
        "extracted_at": context.extracted_at,
        "tokens_saved_estimate": context.tokens_saved_estimate,
        "truncated": context.truncated,
        "split": context.split,
        "chunks": context.chunks,
    }
    # Fire-and-forget token metering (2s, never blocks extraction): counts
    # even cache hits so dashboards can bill per token slice.
    if request.app.state.supabase_client is not None:
        try:
            await asyncio.wait_for(
                increment_token_usage(
                    request.app.state.supabase_client,
                    _metering_identity(request, settings),
                    tokens=context.tokens,
                    mode=context.mode,
                ),
                timeout=DATABASE_TIMEOUT_SECONDS,
            )
        except Exception as error:
            logger.warning("token_metering_failed error_type=%s", type(error).__name__)
    return _rpc_result(
        request_id,
        {
            "content": [{"type": "text", "text": json.dumps(envelope)}],
            "isError": False,
        },
    )


@router.post("/mcp", include_in_schema=False)
async def mcp_messages(request: Request):
    settings: Settings = request.app.state.settings

    if not _origin_is_allowed(request):
        logger.warning("mcp_forbidden_origin origin=%r", request.headers.get("origin", ""))
        return _reject_forbidden_origin()

    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        # Transport-level failure: strict scanners expect HTTP 400 with the
        # standard JSON-RPC envelope (id unknown -> null), not a REST 415.
        return JSONResponse(
            status_code=400,
            content=_rpc_error(
                None,
                INVALID_REQUEST,
                "Invalid Request: Content-Type must be application/json.",
            ),
        )

    if not _accept_header_serves_json(request):
        # The transport requires clients to accept application/json; this
        # server answers with a single JSON response and never opens an SSE
        # stream, so a client that accepts only SSE cannot be served.
        return JSONResponse(
            status_code=406,
            content=_rpc_error(
                None,
                INVALID_REQUEST,
                "Not Acceptable: this server returns single application/json "
                "responses; the Accept header must include application/json.",
            ),
        )

    try:
        payload = json.loads(await request.body())
    except json.JSONDecodeError:
        # Malformed JSON-RPC: HTTP 400 + parse error, id null per spec.
        return JSONResponse(
            status_code=400,
            content=_rpc_error(None, PARSE_ERROR, "Parse error"),
        )

    if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("method"), str):
        request_id = payload.get("id") if isinstance(payload, dict) else None
        return JSONResponse(
            status_code=400,
            content=_rpc_error(request_id, INVALID_REQUEST, "Invalid Request"),
        )

    request_id = payload.get("id")
    if request_id is None:
        # Notification (e.g. notifications/initialized): 202, no body.
        # Authenticated below via tools/call path; capability probes without an
        # id carry no billable work.
        return Response(status_code=202)

    method = payload["method"]
    if method == "initialize":
        # Capability handshake only: returns protocol version + tool *names*,
        # no extraction, no billable work. Public so gateway health-checkers
        # and Test buttons (which omit the upstream token) can validate the
        # endpoint; tools/list and ping below are public discovery too, while
        # tools/call and every other method still require auth.
        if not _accept_header_serves_json(request):
            return _reject_unsupported_accept(request_id)
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return JSONResponse(
                status_code=200,
                content=_rpc_error(request_id, INVALID_PARAMS, "Invalid params: expected an object"),
            )
        return JSONResponse(_initialize_result(settings, request_id, params))

    if method not in PUBLIC_MCP_METHODS:
        # Billable work (tools/call) and any other non-discovery method:
        # X-API-Key or Authorization: Bearer with the scoped or master key.
        # Failures stay inside the JSON-RPC envelope (HTTP 401 + code -32001)
        # so strict validators never see a bare REST {"detail": ...} body.
        try:
            verify_mcp_execution_access(request, settings)
        except HTTPException as error:
            detail = error.detail if isinstance(error.detail, dict) else {"message": str(error.detail)}
            # 401 detail always carries the canonical upgrade_url so agents can
            # print a clickable subscribe link in-chat.
            upgrade_url = detail.get("upgrade_url") or mcp_upgrade_url(settings)
            return JSONResponse(
                status_code=error.status_code,
                content=_rpc_error(
                    request_id,
                    AUTH_REQUIRED,
                    str(detail.get("message") or "Authentication required."),
                    data={
                        "code": detail.get("code") or "premium_required",
                        "hint": detail.get("hint")
                        or f"Send X-API-Key or Authorization: Bearer with the MCP_API_KEY (or master API_KEY). Discovery methods need no key. Subscribe: {upgrade_url}",
                        "upgrade_url": upgrade_url,
                    },
                ),
            )

    if not _accept_header_serves_json(request):
        # See the transport-level check above; initialize is public so the
        # request id is known here and belongs in the envelope.
        return _reject_unsupported_accept(request_id)
    declared_version = _protocol_version_header(request)
    if declared_version not in SUPPORTED_PROTOCOL_VERSIONS:
        logger.info("mcp_unsupported_protocol_version version=%r", declared_version)
        return _reject_unknown_protocol_version(request_id, declared_version)

    params = payload.get("params") or {}
    if not isinstance(params, dict):
        # MCP defines object params only; arrays (by-position) are not used.
        return JSONResponse(_rpc_error(request_id, INVALID_PARAMS, "Invalid params: expected an object"))

    if method == "ping":
        return JSONResponse(_rpc_result(request_id, {}))
    if method == "tools/list":
        return JSONResponse(_tools_list_result(request_id))
    if method == "tools/call":
        result = await _tools_call_result(request, settings, request_id, params)
        # Metering header for marketplaces: approx_tokens/chunks/cache_hit per
        # execution without a second round-trip. Best-effort parse only.
        # `tokens` is mirrored as a deprecated alias for one release.
        response = JSONResponse(result)
        try:
            text = result.get("result", {}).get("content", [{}])[0].get("text", "")
            envelope = json.loads(text) if isinstance(text, str) and text.startswith("{") else {}
            approx = envelope.get("approx_tokens", envelope.get("tokens", 0))
            if isinstance(envelope, dict) and ("approx_tokens" in envelope or "tokens" in envelope):
                response.headers["X-Token-Usage"] = (
                    f"approx_tokens={approx}, "
                    f"tokens={approx}, "
                    f"chunks={envelope.get('chunk_count', 0)}, "
                    f"cache_hit={1 if envelope.get('cache_hit') else 0}"
                )
        except Exception:
            pass
        return response
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
    # dedicated GET /sse path for SSE streaming. Same public empty stream
    # as GET /mcp, Origin checks only.
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
