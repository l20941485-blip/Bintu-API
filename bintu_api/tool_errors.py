"""Tool error compatibility surface for Bintu.

This module keeps legacy tool error imports stable while the centralized error boundary matures.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

from bintu_api.errors.tool_errors import ToolError

__all__ = ["ToolError"]
