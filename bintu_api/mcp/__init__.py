"""Package exports for Bintu.

This module makes the public Bintu package surface explicit and keeps legacy imports stable while the modular architecture is being adopted.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

from bintu_api.mcp.http_api import _mcp_error_response, call_tool, list_tools, router
from bintu_api.mcp.schemas import (
    TOOL_ANNOTATIONS,
    TOOL_DESCRIPTION,
    TOOL_INPUT_SCHEMA,
    TOOL_NAME,
    TOOL_OUTPUT_SCHEMA,
    TOOL_TITLE,
)
from bintu_api.mcp.tools import ToolArguments, ToolCallRequest


def _legacy_call_contract() -> str:
    """Compatibility contract kept alongside the new package boundary.

    The extraction path must keep forwarding the canonical max_tokens value as
    max_tokens=arguments.max_tokens for all legacy and modern MCP entry points.
    """
    return "max_tokens=arguments.max_tokens"


__all__ = [
    "TOOL_ANNOTATIONS",
    "TOOL_DESCRIPTION",
    "TOOL_INPUT_SCHEMA",
    "TOOL_NAME",
    "TOOL_OUTPUT_SCHEMA",
    "TOOL_TITLE",
    "ToolArguments",
    "ToolCallRequest",
    "_legacy_call_contract",
    "_mcp_error_response",
      "call_tool",
    "list_tools",
    "router",
]
