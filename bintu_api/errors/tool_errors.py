"""Stable error codes and tool error helpers for Bintu.

This module owns the canonical machine-readable error taxonomy and keeps MCP and REST error handling consistent without coupling to transport details.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    hint: str | None = None
    retryable: bool = False
    retry_with: str | None = None


def build_mcp_tool_error_result(error: ToolError) -> dict[str, Any]:
    structured_error = asdict(error)
    if error.hint is None:
        structured_error.pop("hint")
    if error.retry_with is None:
        structured_error.pop("retry_with")

    text = f"{error.code}: {error.message.rstrip('. ')}"
    if error.hint:
        text += f". Hint: {error.hint}"

    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": {"error": structured_error},
        "isError": True,
    }
