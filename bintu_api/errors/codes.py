"""Stable error codes and tool error helpers for Bintu.

This module owns the canonical machine-readable error taxonomy and keeps MCP and REST error handling consistent without coupling to transport details.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

import re

ERROR_CODES = frozenset(
    {
        "auth_misconfiguration",
        "blocked_by_robots",
        "burst_rate_limit_exceeded",
        "email_not_verified",
        "internal_error",
        "invalid_api_key",
        "invalid_arguments",
        "invalid_max_tokens",
        "invalid_or_unsafe_url",
        "invalid_session",
        "invalid_token_budget",
        "invalid_tool_arguments",
        "mobile_auth_not_configured",
        "mobile_auth_unavailable",
        "payload_too_large",
        "premium_required",
        "reader_auth_required",
        "reader_document_empty",
        "reader_document_too_large",
        "reader_identity_required",
        "reader_snapshot_unavailable",
        "redirect_to_private_network",
        "render_js_disabled",
        "robots_unreachable",
        "too_many_redirects",
        "unknown_tool",
        "unsupported_content_encoding",
        "unsupported_media_type",
        "upstream_access_denied",
        "upstream_connection_error",
        "upstream_http_error",
        "upstream_rate_limited",
        "upstream_render_error",
        "upstream_timeout",
    }
)


def normalize_error_code(code: str | None) -> str:
    """Normalize a caller-provided error code to Bintu's canonical snake_case form."""
    if not isinstance(code, str) or not code.strip():
        raise ValueError("error code must be a non-empty string")

    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", code.strip())
    normalized = normalized.replace("-", "_").replace(" ", "_")
    normalized = re.sub(r"[^a-zA-Z0-9_]+", "_", normalized).lower()
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized

