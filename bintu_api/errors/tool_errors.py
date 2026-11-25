"""Stable error codes and tool error helpers for Bintu.

This module owns the canonical machine-readable error taxonomy and keeps MCP and REST error handling consistent without coupling to transport details.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

import re
from dataclasses import asdict, dataclass
from typing import Any

from bintu_api.errors.codes import ERROR_CODES, normalize_error_code


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    hint: str | None = None
    retryable: bool = False
    retry_with: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code.strip():
            raise ValueError("error code must be a non-empty string")
        object.__setattr__(self, "code", normalize_error_code(self.code))
        if self.code not in ERROR_CODES:
            # Keep compatibility for extension errors while still enforcing a
            # stable snake_case shape. Unknown codes are preserved as-is so
            # legacy callers do not crash during migration.
            object.__setattr__(self, "code", re.sub(r"[^a-z0-9_]+", "_", self.code.lower()).strip("_"))
        if not isinstance(self.message, str):
            object.__setattr__(self, "message", str(self.message))
        if self.hint is not None and not isinstance(self.hint, str):
            object.__setattr__(self, "hint", str(self.hint))
        if self.retry_with is not None and not isinstance(self.retry_with, str):
            object.__setattr__(self, "retry_with", str(self.retry_with))




_RETRY_AFTER_DELAY_CODES = frozenset({
    "upstream_rate_limited",
    "upstream_service_unavailable",
})
_RETRY_LATER_CODES = frozenset({
    "upstream_timeout",
    "upstream_connection_error",
    "robots_unreachable",
})
_RENDER_JS_FALLBACK_CODES = frozenset({
    "render_js_disabled",
    "upstream_render_error",
})


def retry_policy_for_code(code: str) -> tuple[bool, str | None]:
    """Return canonical (retryable, retry_with) metadata for an error code."""
    normalized = normalize_error_code(code) if isinstance(code, str) and code.strip() else ""
    if normalized in _RETRY_AFTER_DELAY_CODES:
        return True, "retry_after_delay"
    if normalized in _RETRY_LATER_CODES:
        return True, "retry_later"
    if normalized in _RENDER_JS_FALLBACK_CODES:
        return False, "render_js=false"
    return False, None


def build_mcp_tool_error_result(error: ToolError) -> dict[str, Any]:
    structured_error = asdict(error)
    if error.hint is None:
        structured_error.pop("hint")
    if error.retry_with is None:
        structured_error.pop("retry_with")

    text = f"{error.code}: {error.message.rstrip('. ')}"
    if error.hint:
        text += f". Hint: {error.hint}"
    if error.retry_with:
        text += f". Retry with: {error.retry_with}"

    return {
        "content": [{"type": "text", "text": text}],
        "structuredContent": {"error": structured_error},
        "isError": True,
    }
