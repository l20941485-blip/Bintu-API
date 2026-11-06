"""Standard MCP Streamable HTTP endpoint (JSON-RPC 2.0, stateless).

Exposes the single ``bintu_scrape_text`` tool to real MCP clients â€” Claude
custom connectors (web and Desktop, both account-brokered), Claude Code, and
any other Streamable HTTP client â€” without adding the ``mcp`` SDK dependency.
Targets protocol revision ``2025-11-25`` (also accepting ``2025-06-18`` and
``2025-03-26`` during negotiation):

- POST /mcp accepts one JSON-RPC message per request and answers with a
  single ``application/json`` response (the spec allows skipping SSE when
  the server never pushes messages). ``initialize``, ``tools/list`` and
  ``ping`` are public discovery/onboarding methods (protocol negotiation,
  tool schemas, liveness â€” never extraction); every other method â€” above
  all ``tools/call`` â€” requires the master API_KEY, the scoped
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
the model can self-correct â€” e.g. retrying with ``render_js=false``.
"""

import asyncio
import json
import logging
import socket
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from bintu_api import routes
from bintu_api.auth import (
    mcp_rate_limit_identity,
    mcp_upgrade_url,
    verify_mcp_execution_access,
)
from bintu_api.context import (
    CacheEconomics,
    _decode_source_text,
    extract_context,
    normalize_mode,
)
from bintu_api.errors.tool_errors import build_mcp_tool_error_result
from bintu_api.mcp.protocol import (
    AUTH_REQUIRED,
    INVALID_PARAMS,
    INVALID_REQUEST,
    MAX_MCP_BODY_BYTES as _PROTOCOL_MAX_MCP_BODY_BYTES,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PUBLIC_MCP_METHODS,
    SUPPORTED_PROTOCOL_VERSIONS,
    UPSTREAM_ACCESS_DENIED_STATUSES,
)
from bintu_api.mcp.protocol import (
    _accept_header_serves_json as _protocol_accept_header_serves_json,
)
from bintu_api.mcp.protocol import (
    _empty_sse_stream as _protocol_empty_sse_stream,
)
from bintu_api.mcp.protocol import (
    _failure_code_for_error as _protocol_failure_code_for_error,
)
from bintu_api.mcp.protocol import (
    _initialize_result as _protocol_initialize_result,
)
from bintu_api.mcp.protocol import (
    _origin_is_allowed as _protocol_origin_is_allowed,
)
from bintu_api.mcp.protocol import (
    _protocol_version_header as _protocol_version_header_value,
)
from bintu_api.mcp.protocol import (
    _read_mcp_body as _protocol_read_mcp_body,
)
from bintu_api.mcp.protocol import (
    _reject_forbidden_origin as _protocol_reject_forbidden_origin,
)
from bintu_api.mcp.protocol import (
    _reject_unknown_protocol_version as _protocol_reject_unknown_protocol_version,
)
from bintu_api.mcp.protocol import (
    _reject_unsupported_accept as _protocol_reject_unsupported_accept,
)
from bintu_api.mcp.protocol import (
    _rpc_error as _protocol_rpc_error,
)
from bintu_api.mcp.protocol import (
    _rpc_result as _protocol_rpc_result,
)
from bintu_api.mcp.protocol import (
    _tools_list_result as _protocol_tools_list_result,
)
from bintu_api.mcp.schemas import TOOL_NAME
from bintu_api.mcp.tools import ToolArguments
from bintu_api.observability import (
    log_extraction_completed,
    log_extraction_failed,
)
from bintu_api.scraper import (
    PayloadTooLarge,
    TargetURLRejected,
    TooManyRedirects,
    UnsupportedContentEncoding,
    UnsupportedMediaType,
    UpstreamHTTPError,
    UpstreamRenderError,
)
from bintu_api.settings import Settings
from bintu_api.tool_errors import ToolError

MAX_MCP_BODY_BYTES = _PROTOCOL_MAX_MCP_BODY_BYTES

logger = logging.getLogger("bintu_api.mcp_streamable")

router = APIRouter(tags=["MCP"])


def _rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return _protocol_rpc_result(request_id, result)


def _rpc_error(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    return _protocol_rpc_error(request_id, code, message, data)


def _tool_error_result(error: ToolError) -> dict[str, Any]:
    return build_mcp_tool_error_result(error)


def _tool_error_for_http_exception(error: HTTPException) -> ToolError:
    detail = error.detail if isinstance(error.detail, dict) else {}
    code = detail.get("code")
    message = detail.get("message")
    hint = detail.get("hint")

    if code == "render_js_disabled":
        return ToolError(
            "render_js_disabled",
            "JavaScript rendering is disabled on this service.",
            "Retry with render_js=false for plain HTML extraction.",
            retry_with="render_js=false",
        )
    if code == "invalid_or_unsafe_url":
        return ToolError(
            "invalid_or_unsafe_url",
            "The target URL is invalid or unsafe.",
            "Use an absolute public HTTP or HTTPS URL.",
        )
    if code == "robots_unreachable":
        return ToolError(
            "upstream_connection_error",
            str(message or "The site's robots.txt could not be retrieved."),
            str(hint or "Retry later or use another public URL."),
            retryable=True,
            retry_with="retry_later",
        )
    if code == "blocked_by_robots":
        return ToolError(
            "upstream_access_denied",
            str(message or "The site does not permit this request."),
            str(hint or "Respect the site's robots.txt rules."),
        )
    if code == "burst_rate_limit_exceeded":
        return ToolError(
            "upstream_rate_limited",
            str(message or "The request rate limit was exceeded."),
            "Wait for the Retry-After interval before retrying.",
            retryable=True,
            retry_with="retry_after_delay",
        )

    if isinstance(code, str) and code in {
        "invalid_arguments",
        "invalid_or_unsafe_url",
        "unsupported_media_type",
        "unsupported_content_encoding",
        "payload_too_large",
        "too_many_redirects",
        "upstream_http_error",
        "upstream_rate_limited",
        "upstream_access_denied",
        "upstream_timeout",
        "upstream_connection_error",
        "upstream_render_error",
        "render_js_disabled",
    }:
        retryable = code in {
            "upstream_rate_limited",
            "upstream_timeout",
            "upstream_connection_error",
        } or (code == "upstream_http_error" and error.status_code >= 500)
        retry_with = (
            "retry_after_delay"
            if code == "upstream_rate_limited"
            else "retry_later"
            if retryable
            else "render_js=false"
            if code in {"render_js_disabled", "upstream_render_error"}
            else None
        )
        return ToolError(
            code,
            str(message or "The tool request could not be completed."),
            str(hint) if hint else None,
            retryable=retryable,
            retry_with=retry_with,
        )

    if error.status_code == 413:
        return ToolError("payload_too_large", "The page exceeds the 1 MiB size limit.")
    if error.status_code == 415:
        return ToolError(
            "unsupported_media_type",
            "Only HTML and XHTML pages are supported.",
            "Use a public HTML page.",
        )
    if error.status_code == 429:
        return ToolError(
            "upstream_rate_limited",
            "The target is rate limiting requests.",
            "Retry after a short delay or use another public URL.",
            retryable=True,
            retry_with="retry_after_delay",
        )
    if error.status_code in {401, 402, 403}:
        return ToolError(
            "upstream_access_denied",
            "The target denied access.",
            "Try another public URL.",
        )
    if error.status_code == 504:
        return ToolError(
            "upstream_timeout",
            "The target did not respond in time.",
            "Retry later or use another public URL.",
            retryable=True,
            retry_with="retry_later",
        )
    if error.status_code == 400:
        return ToolError(
            "invalid_arguments",
            str(message or "The tool request is invalid."),
            str(hint) if hint else "Check the tool inputs and retry.",
        )
    return ToolError(
        "upstream_connection_error",
        "The target could not be reached.",
        "Retry later or use another public URL.",
        retryable=True,
        retry_with="retry_later",
    )


def _tool_error_for_extraction_exception(error: Exception) -> ToolError:
    if isinstance(error, UpstreamHTTPError):
        if error.status_code == 429:
            return ToolError(
                "upstream_rate_limited",
                f"The target returned HTTP {error.status_code} and is rate limiting requests.",
                "Retry after a short delay or use another public URL.",
                retryable=True,
                retry_with="retry_after_delay",
            )
        if error.status_code in UPSTREAM_ACCESS_DENIED_STATUSES:
            return ToolError(
                "upstream_access_denied",
                f"The target returned HTTP {error.status_code} and denied access.",
                "Try another public URL.",
            )
        retryable = error.status_code >= 500
        return ToolError(
            "upstream_http_error",
            f"The target returned HTTP {error.status_code}.",
            "Retry later or use another public URL.",
            retryable=retryable,
            retry_with="retry_later" if retryable else None,
        )
    if isinstance(error, UnsupportedMediaType):
        return ToolError(
            "unsupported_media_type",
            "Only HTML and XHTML pages are supported.",
            "Use a public HTML page.",
        )
    if isinstance(error, UnsupportedContentEncoding):
        return ToolError(
            "unsupported_content_encoding",
            "The target returned an unsupported or invalid compressed response.",
            "Use a page served with a supported content encoding.",
        )
    if isinstance(error, PayloadTooLarge):
        return ToolError(
            "payload_too_large",
            "The page exceeds the 1 MiB size limit.",
            "Try a smaller page.",
        )
    if isinstance(error, TooManyRedirects):
        return ToolError(
            "too_many_redirects",
            "The page has too many redirects.",
            "Try the final destination URL.",
        )
    if isinstance(error, UpstreamRenderError):
        return ToolError(
            "upstream_render_error",
            "The target page could not be rendered.",
            "Retry with render_js=false for plain HTML extraction.",
            retry_with="render_js=false",
        )
    if isinstance(error, (TimeoutError, socket.timeout)):
        return ToolError(
            "upstream_timeout",
            "The target did not respond in time.",
            "Retry later or use another public URL.",
            retryable=True,
            retry_with="retry_later",
        )
    return ToolError(
        "upstream_connection_error",
        "Could not connect to the target.",
        "The target server may be unavailable; retry later or use another public URL.",
        retryable=True,
        retry_with="retry_later",
    )


async def _read_mcp_body(request: Request) -> bytes | None:
    return await _protocol_read_mcp_body(request)


def _protocol_version_header(request: Request) -> str:
    return _protocol_version_header_value(request)


def _reject_unknown_protocol_version(request_id: Any, version: str) -> JSONResponse:
    # Strict scanners expect the standard JSON-RPC envelope even for
    # transport-level rejections â€” never a bare {"error": ...} shape.
    return _protocol_reject_unknown_protocol_version(request_id, version)


def _accept_header_serves_json(request: Request) -> bool:
    """True unless the client explicitly refuses application/json responses.

    The transport requires clients to send ``Accept: application/json,
    text/event-stream``. This server answers every POST with a single JSON
    response and never opens an SSE stream, so a client that lists other
    media types but not JSON cannot be served (HTTP 406). Clients that send
    no Accept header at all (gateway Test buttons, curl) are tolerated â€”
    rejecting the largest installed base would be worse than the
    corner-case protocol violation.
    """
    return _protocol_accept_header_serves_json(request)


def _reject_unsupported_accept(request_id: Any) -> JSONResponse:
    return _protocol_reject_unsupported_accept(request_id)


def _reject_forbidden_origin() -> JSONResponse:
    return _protocol_reject_forbidden_origin()


async def _empty_sse_stream(request: Request) -> Response:
    """Shared handler for GET /mcp and its /sse aliases (stateless: empty stream).

    GET is the tokenless liveness surface: gateway health-checkers and
    marketplace audits probe it without credentials, and no extraction ever
    happens here, so auth is intentionally skipped (POST tools/call stays
    gated). Origin is still validated against DNS rebinding.
    """
    return await _protocol_empty_sse_stream(request)


def _origin_is_allowed(request: Request) -> bool:
    """Validate the Origin header against DNS-rebinding attacks.

    Absent Origin (non-browser clients such as Claude Code or curl) is
    allowed. When present, the origin must match the request's own scheme +
    host; anything else is rejected with 403 per the Streamable HTTP spec.
    """
    return _protocol_origin_is_allowed(request)


def _failure_code_for_error(error: Exception) -> str:
    """Map an upstream extraction exception to a stable privacy-safe code."""
    return _protocol_failure_code_for_error(error)


def _initialize_result(settings: Settings, request_id: Any, params: dict[str, Any]) -> dict[str, Any]:
    return _protocol_initialize_result(settings, request_id, params)


def _tools_list_result(request_id: Any) -> dict[str, Any]:
    return _protocol_tools_list_result(request_id)


async def _tools_call_result(
    request: Request,
    settings: Settings,
    request_id: Any,
    params: dict[str, Any],
) -> dict[str, Any]:
    if params.get("name") != TOOL_NAME:
        return _rpc_error(
            request_id,
            INVALID_PARAMS,
            f"Unknown tool: {params.get('name')}",
        )

    raw_arguments = params.get("arguments") or {}
    if isinstance(raw_arguments, dict):
        # Canonicalize pitch-name aliases BEFORE Pydantic validation so raw
        # JSON-RPC calls benefit too; canonical max_tokens wins on conflict.
        raw_arguments = dict(raw_arguments)
        if "mode" in raw_arguments:
            try:
                raw_arguments["mode"] = normalize_mode(raw_arguments["mode"])
            except ValueError as error:
                return _rpc_result(
                    request_id,
                    _tool_error_result(
                        ToolError(
                            "invalid_arguments",
                            f"Invalid mode: {error}",
                            "Use scrape, chunk, or summarize.",
                        )
                    ),
                )
        if "chunk_token_budget" in raw_arguments:
            if "max_tokens" in raw_arguments:
                logger.warning("mcp_alias_conflict canonical=max_tokens wins over chunk_token_budget")
                raw_arguments.pop("chunk_token_budget")
            else:
                raw_arguments["max_tokens"] = raw_arguments.pop("chunk_token_budget")

    try:
        arguments = ToolArguments.model_validate(raw_arguments)
    except ValidationError as error:
        first = error.errors()[0]
        location = ".".join(str(part) for part in first.get("loc", ())) or "arguments"
        return _rpc_result(
            request_id,
            _tool_error_result(
                ToolError(
                    "invalid_arguments",
                    f"Invalid value for {location}: {first['msg']}",
                    "Check the tool input schema and retry.",
                )
            ),
        )

    if arguments.render_js and not settings.render_js_enabled:
        log_extraction_failed(
            request_id=getattr(getattr(request, "state", None), "request_id", None),
            url=arguments.url,
            mode=arguments.mode,
            failure_code="render_js_disabled",
            error_type="ServiceConfigurationError",
        )
        return _rpc_result(
            request_id,
            _tool_error_result(
                ToolError(
                    "render_js_disabled",
                    "JavaScript rendering is disabled on this service.",
                    "Retry with render_js=false for plain HTML extraction.",
                    retry_with="render_js=false",
                )
            ),
        )

    try:
        await asyncio.to_thread(
            request.app.state.rate_limiter.check,
            mcp_rate_limit_identity(request, settings),
        )
    except HTTPException as error:
        return _rpc_result(
            request_id,
            _tool_error_result(_tool_error_for_http_exception(error)),
        )

    extraction_started_at = time.perf_counter()

    try:
        # MCP tool calls use the same robots, cache, SSRF-guarded page fetch,
        # and extractor pipeline as the REST endpoint. Call through the routes
        # module so tests can patch the shared network boundary at
        # bintu_api.routes.fetch_html_document.
        document, cached, cache_layer = await routes._fetch_and_extract(
            request,
            arguments.url,
            include_nav=False,
            include_header=False,
            include_footer=False,
            render_js=arguments.render_js,
            links=arguments.links,
            skip_cache=not arguments.cache,
            persist=arguments.persist,
            mode=arguments.mode,
            max_tokens=arguments.max_tokens,
            footnote_url_policy=arguments.footnote_url_policy,
            max_footnote_url_length=arguments.max_footnote_url_length,
        )
    except TargetURLRejected as error:
        log_extraction_failed(
            request_id=getattr(getattr(request, "state", None), "request_id", None),
            url=arguments.url,
            mode=arguments.mode,
            failure_code="invalid_or_unsafe_url",
            error_type=type(error).__name__,
            duration_ms=(time.perf_counter() - extraction_started_at) * 1000,
        )
        logger.info("mcp_tool_error detail=%r", str(error))
        return _rpc_result(
            request_id,
            _tool_error_result(
                ToolError(
                    "invalid_or_unsafe_url",
                    "The target URL is invalid or unsafe.",
                    "Use an absolute public HTTP or HTTPS URL.",
                )
            ),
        )
    except HTTPException as error:
        tool_error = _tool_error_for_http_exception(error)
        log_extraction_failed(
            request_id=getattr(getattr(request, "state", None), "request_id", None),
            url=arguments.url,
            mode=arguments.mode,
            failure_code=tool_error.code,
            error_type=type(error).__name__,
            duration_ms=(time.perf_counter() - extraction_started_at) * 1000,
            status_code=error.status_code,
        )
        logger.info("mcp_tool_error detail=%r", error.detail)
        return _rpc_result(
            request_id,
            _tool_error_result(tool_error),
        )
    except (
        UnsupportedMediaType,
        UnsupportedContentEncoding,
        PayloadTooLarge,
        UpstreamHTTPError,
        TooManyRedirects,
        UpstreamRenderError,
        TimeoutError,
        OSError,
    ) as error:
        failure_code = _failure_code_for_error(error)
        log_extraction_failed(
            request_id=getattr(getattr(request, "state", None), "request_id", None),
            url=arguments.url,
            mode=arguments.mode,
            failure_code=failure_code,
            error_type=type(error).__name__,
            duration_ms=(time.perf_counter() - extraction_started_at) * 1000,
            status_code=getattr(error, "status_code", None),
        )
        logger.info("mcp_tool_error error_type=%s", type(error).__name__)

        return _rpc_result(
            request_id,
            _tool_error_result(_tool_error_for_extraction_exception(error)),
        )

    # Preserve the original extraction economics when serving from the
    # persistent cache. The cached row no longer contains source HTML, so
    # recomputing these values would incorrectly report zero savings.
    from bintu_api.extraction.cache import build_cache_economics

    cache_economics = build_cache_economics(document, cached, cache_layer)

    try:
        from bintu_api.extraction.pipeline import run_extraction

        context = await run_extraction(
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
            raw_text=cached.markdown,
            content_truncated=cached.truncated,
            html_source_text=(_decode_source_text(document) if document is not None else ""),
            cache_hit=cache_layer != "none",
            cache_layer=cache_layer,
            document=document,
            settings=settings,
            cache_economics=cache_economics,
            extracted_at=cached.extracted_at,
        )
    except HTTPException as error:
        tool_error = _tool_error_for_http_exception(error)
        log_extraction_failed(
            request_id=getattr(getattr(request, "state", None), "request_id", None),
            url=arguments.url,
            mode=arguments.mode,
            failure_code=tool_error.code,
            error_type=type(error).__name__,
            duration_ms=(time.perf_counter() - extraction_started_at) * 1000,
            status_code=error.status_code,
        )
        logger.info("mcp_tool_error detail=%r", error.detail)
        return _rpc_result(
            request_id,
            _tool_error_result(tool_error),
        )

    log_extraction_completed(
        request_id=getattr(getattr(request, "state", None), "request_id", None),
        url=arguments.url,
        mode=context.mode,
        cache_hit=context.cache_hit,
        cache_layer=context.cache_layer,
        approx_tokens=context.approx_tokens,
        html_tokens=context.html_tokens,
        tokens_saved_estimate=context.tokens_saved_estimate,
        truncated=context.truncated,
        limiting_factor=context.limiting_factor,
    )

    # Unified Token Tax envelope in content[0].text across ALL modes for
    # predictable context budgets (no tier caps in code; dashboards own quota).
    # `tokens` is a deprecated alias of `approx_tokens` (kept for one release);
    # `token_method` names the counter; `html_tokens` is the fetched-document
    # baseline for `tokens_saved_estimate`; `limiting_factor` says which cap bound.
    # provenance is added additively (Phase D): same shape as REST response.
    from bintu_api.extraction.response import build_mcp_envelope

    envelope = build_mcp_envelope(context, arguments.url)
    return _rpc_result(
        request_id,
        {
            "content": [{"type": "text", "text": json.dumps(envelope)}],
            # MCP clients validate this against TOOL_OUTPUT_SCHEMA when the
            # tool declares an outputSchema. Keep the human-readable JSON in
            # content[0].text while exposing the same envelope structurally.
            "structuredContent": envelope,
            "isError": False,
        },
    )


@router.post("/mcp", include_in_schema=False)
async def mcp_messages(request: Request):
    settings: Settings = request.app.state.settings

    if not _origin_is_allowed(request):
        logger.warning(
            "mcp_forbidden_origin origin=%r",
            request.headers.get("origin", ""),
        )
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
        # The transport requires clients to accept application/json; this server
        # answers with a single JSON response and never opens an SSE stream, so
        # a client that accepts only SSE cannot be served.
        return JSONResponse(
            status_code=406,
            content=_rpc_error(
                None,
                INVALID_REQUEST,
                "Invalid Request: Content-Type must be application/json.",
            ),
        )

    body = await _read_mcp_body(request)
    if body is None:
        return JSONResponse(
            status_code=413,
            content=_rpc_error(None, INVALID_REQUEST, "Request body too large."),
        )

    try:
        payload = json.loads(body)
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
                content=_rpc_error(
                    request_id,
                    INVALID_PARAMS,
                    "Invalid params: expected an object",
                ),
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
                        or "Send X-API-Key or Authorization: Bearer with the MCP_API_KEY (or master API_KEY). Discovery methods need no key. Subscribe: "
                        + upgrade_url,
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
        logger.info(
            "mcp_unsupported_protocol_version version=%r",
            declared_version,
        )
        return _reject_unknown_protocol_version(request_id, declared_version)

    params = payload.get("params") or {}
    if not isinstance(params, dict):
        # MCP defines object params only; arrays (by-position) are not used.
        return JSONResponse(
            _rpc_error(
                request_id,
                INVALID_PARAMS,
                "Invalid params: expected an object",
            )
        )

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
                response.headers["X-Token-Usage"] = str(max(0, int(approx)))
                response.headers["X-Mode"] = str(envelope.get("mode", ""))
        except Exception:
            pass
        return response

    if method.startswith("notifications/"):
        # Tolerate a client sending a notification with an id attached.
        return JSONResponse(_rpc_result(request_id, {}))

    return JSONResponse(
        _rpc_error(
            request_id,
            METHOD_NOT_FOUND,
            f"Method not found: {method}",
        )
    )


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


@router.api_route(
    "/mcp",
    methods=["DELETE", "PUT", "PATCH"],
    include_in_schema=False,
)
async def mcp_unsupported_methods() -> Response:
    # Stateless server: no sessions to end (DELETE); PUT/PATCH are undefined.
    return Response(status_code=405, headers={"Allow": "POST, GET"})
