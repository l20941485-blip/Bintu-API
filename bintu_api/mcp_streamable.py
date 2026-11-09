"""Legacy compatibility module for the MCP Streamable HTTP transport.

New code should import from ``bintu_api.mcp.streamable``. This module preserves
the historical import paths used by the application, stdio entry point, and
transport contract tests.
"""

from bintu_api.mcp.streamable import (
    MAX_MCP_BODY_BYTES,
    _initialize_result,
    _rpc_error,
    _rpc_result,
    _tools_call_result,
    _tools_list_result,
    router,
)

__all__ = [
    "MAX_MCP_BODY_BYTES",
    "_initialize_result",
    "_rpc_error",
    "_rpc_result",
    "_tools_call_result",
    "_tools_list_result",
    "router",
]
