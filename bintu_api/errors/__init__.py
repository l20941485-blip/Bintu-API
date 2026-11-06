"""Package exports and compatibility shims for Bintu.

This module makes the public Bintu package surface explicit and keeps legacy imports stable while the modular architecture is being adopted.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

from bintu_api.errors.codes import ERROR_CODES
from bintu_api.errors.tool_errors import ToolError, build_mcp_tool_error_result

__all__ = ["ERROR_CODES", "ToolError", "build_mcp_tool_error_result"]
