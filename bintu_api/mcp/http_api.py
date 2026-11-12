"""MCP-compatible tool discovery and invocation helpers.


Two surfaces intentionally share the same tool definitions:


- /mcp/tools and /mcp/tools/call are legacy JSON helper endpoints.
- /mcp is the standard stateless Streamable HTTP endpoint implemented in
  bintu_api.mcp.streamable.


Successful tool calls expose the extraction envelope as structuredContent
and preserve its JSON representation in content[0].text.
"""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Security
from pydantic import ValidationError

from bintu_api.api import mcp_adapter
from bintu_api.mcp.schemas import (
    TOOL_ANNOTATIONS,
    TOOL_DESCRIPTION,
    TOOL_INPUT_SCHEMA,
    TOOL_NAME,
    TOOL_OUTPUT_SCHEMA,
    TOOL_TITLE,
)
from bintu_api.mcp.tools import ToolArguments, ToolCallRequest
from bintu_api.observability import log_extraction_completed
from bintu_api.security.auth import (
    api_key_scheme,
    mcp_rate_limit_identity,
    verify_mcp_api_access,
)
from bintu_api.settings import Settings

router = APIRouter(prefix="/mcp", tags=["MCP"])


logger = logging.getLogger("bintu_api.mcp")




def _mcp_error_response(
    code: str,
    message: str,
    hint: str,
) -> dict[str, Any]:
    """Return a stable in-band tool error."""
    logger.info("mcp_tool_error code=%s", code)
    return {
        "content": [
            {
                "type": "text",
                "text": f"{code}: {message} {hint}".strip(),
            }
        ],
        "isError": True,
    }


@router.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    return {
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
    }


@router.post(
    "/tools/call",
    dependencies=[Security(api_key_scheme, scopes=[])],
)
async def call_tool(
    payload: ToolCallRequest,
    request: Request,
) -> dict[str, Any]:
    settings: Settings = request.app.state.settings
    verify_mcp_api_access(request, settings)

    if payload.name != TOOL_NAME:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "unknown_tool",
                "message": f"Unknown MCP tool: {payload.name}.",
                "hint": f"Use the supported tool: {TOOL_NAME}.",
            },
        )

    try:
        arguments = ToolArguments.model_validate(payload.arguments)
    except ValidationError as error:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_tool_arguments",
                "message": "The tool arguments are invalid.",
                "hint": "Check the tool input schema and retry.",
                "errors": error.errors(),
            },
        ) from error

    if arguments.render_js and not settings.render_js_enabled:
        return _mcp_error_response(
            "render_js_disabled",
            "JavaScript rendering is disabled on this service.",
            "Retry with render_js=false for plain HTML extraction.",
        )

    await asyncio.to_thread(
        request.app.state.rate_limiter.check,
        mcp_rate_limit_identity(request, settings),
    )

    sections = arguments.sections

    try:
        document, cached, cache_layer = await mcp_adapter.fetch_and_extract(
            request,
            arguments.url,
            include_nav=False,
            include_header=False,
            include_footer=False,
            render_js=arguments.render_js,
            skip_cache=not arguments.cache,
            persist=arguments.persist,
            mode=arguments.mode,
            max_tokens=arguments.max_tokens,
            links=arguments.links,
            footnote_url_policy=arguments.footnote_url_policy,
            max_footnote_url_length=arguments.max_footnote_url_length,
            sections=sections,
            )

    except mcp_adapter.TargetURLRejected as error:
        return _mcp_error_response(
            "invalid_or_unsafe_url",
            str(error),
            "URL must start with http:// or https:// and be publicly accessible.",
        )
    except HTTPException as error:
        detail = error.detail
        if isinstance(detail, dict) and isinstance(
            detail.get("code"),
            str,
        ):
            return _mcp_error_response(
                detail["code"],
                str(detail.get("message", "Extraction failed.")),
                str(detail.get("hint", "")).strip(),
            )
        raise

    cache_economics = mcp_adapter.build_cache_economics(document, cached, cache_layer)



    context = await mcp_adapter.run_extraction(
        request,
        arguments.url,
        mode=arguments.mode,
        max_tokens=arguments.max_tokens,
        sections=sections,
        cache=arguments.cache,
        render_js=arguments.render_js,
        include_nav=False,
        include_header=False,
        include_footer=False,
        identity=mcp_rate_limit_identity(request, settings),
        raw_text=cached.markdown,
        content_truncated=cached.truncated,
        html_source_text=(mcp_adapter.decode_source_text(document) if document is not None else ""),
        cache_hit=cache_layer != "none",
        cache_layer=cache_layer,
        document=document,
        settings=settings,
        cache_economics=cache_economics,
        extracted_at=cached.extracted_at,
    )

    log_extraction_completed(
        request_id=getattr(
            getattr(request, "state", None),
            "request_id",
            None,
        ),
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



    envelope = mcp_adapter.build_mcp_envelope(context, arguments.url)

    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(envelope),
            }
        ],
        "structuredContent": envelope,
        "isError": False,
    }




