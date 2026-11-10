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

__all__ = [
    "TOOL_ANNOTATIONS",
    "TOOL_DESCRIPTION",
    "TOOL_INPUT_SCHEMA",
    "TOOL_NAME",
    "TOOL_OUTPUT_SCHEMA",
    "TOOL_TITLE",
    "ToolArguments",
    "ToolCallRequest",
    "_mcp_error_response",
      "call_tool",
    "list_tools",
    "router",
]
