"""Simple MCP-compatible tool discovery and invocation endpoints."""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, ValidationError

from bintu_api.auth import rate_limit_identity, verify_api_access
from bintu_api.routes import _scrape_text
from bintu_api.settings import Settings


router = APIRouter(prefix="/mcp", tags=["MCP"])
TOOL_NAME = "bintu_scrape_text"
TOOL_DESCRIPTION = "Extracts token-optimized Markdown from any public web page."


class ToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any]


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    render_js: bool = False


@router.get("/tools")
async def list_tools(request: Request) -> dict[str, Any]:
    verify_api_access(request, request.app.state.settings)
    return {
        "tools": [
            {
                "name": TOOL_NAME,
                "description": TOOL_DESCRIPTION,
                "inputSchema": {
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
                },
            }
        ]
    }


@router.post("/tools/call")
async def call_tool(payload: ToolCallRequest, request: Request) -> dict[str, list[dict[str, str]]]:
    settings: Settings = request.app.state.settings
    verify_api_access(request, settings)
    if payload.name != TOOL_NAME:
        raise HTTPException(status_code=400, detail=f"Unknown MCP tool: {payload.name}")
    try:
        arguments = ToolArguments.model_validate(payload.arguments)
    except ValidationError as error:
        raise HTTPException(status_code=400, detail=error.errors()) from error

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
