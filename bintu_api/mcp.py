"""Simple MCP-compatible tool discovery and invocation endpoints.

Two surfaces exist on purpose:

- ``/mcp/tools`` and ``/mcp/tools/call``: minimal JSON helpers with the same
  shapes as MCP content blocks; kept for the existing RapidAPI listing and
  any integrations written against them.
- ``/mcp`` (bintu_api.mcp_streamable): the standard MCP Streamable HTTP
  endpoint (JSON-RPC 2.0, stateless) used by Claude connectors and Claude
  Code. Tool definitions are shared via TOOL_NAME/TOOL_DESCRIPTION/
  TOOL_INPUT_SCHEMA so both surfaces stay in lockstep.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request, Security
from pydantic import BaseModel, ConfigDict, ValidationError

from bintu_api.auth import (
    api_key_scheme,
    rate_limit_identity,
    verify_mcp_api_access,
)
from bintu_api.routes import _scrape_text
from bintu_api.settings import Settings


router = APIRouter(prefix="/mcp", tags=["MCP"])
TOOL_NAME = "bintu_scrape_text"
TOOL_DESCRIPTION = "Extracts readable text from a public web page (plain HTML; JS rendering disabled unless enabled)."
TOOL_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "url": {
            "type": "string",
            "description": "Public HTTP or HTTPS URL to extract.",
        },
        "render_js": {
            "type": "boolean",
            "default": False,
            "description": "Render the page in Chromium before extracting text.",
        },
    },
    "required": ["url"],
    "additionalProperties": False,
}


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any]


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    render_js: bool = False


@router.get(
    "/tools",
    dependencies=[Security(api_key_scheme, scopes=[])],
)
async def list_tools(request: Request) -> dict[str, Any]:
    verify_mcp_api_access(request, request.app.state.settings)
    return {
        "tools": [
            {
                "name": TOOL_NAME,
                "description": TOOL_DESCRIPTION,
                "inputSchema": TOOL_INPUT_SCHEMA,
            }
        ]
    }


@router.post(
    "/tools/call",
    dependencies=[Security(api_key_scheme, scopes=[])],
)
async def call_tool(payload: ToolCallRequest, request: Request) -> dict[str, list[dict[str, str]]]:
    settings: Settings = request.app.state.settings
    verify_mcp_api_access(request, settings)
    if payload.name != TOOL_NAME:
        raise HTTPException(status_code=400, detail=f"Unknown MCP tool: {payload.name}")
    try:
        arguments = ToolArguments.model_validate(payload.arguments)
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=error.errors()) from error

    if arguments.render_js and not settings.render_js_enabled:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "render_js_disabled",
                "message": "JavaScript rendering is disabled on this service.",
                "hint": "Retry with render_js=false for plain HTML extraction.",
            },
        )

    result = await _scrape_text(
        request,
        arguments.url,
        include_nav=False,
        include_header=False,
        include_footer=False,
        identity=rate_limit_identity(request, settings),
        render_js=arguments.render_js,
    )
    return {"content": [{"type": "text", "text": result.text}]}
