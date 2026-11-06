"""Extraction orchestration and response-shaping helpers.

This package owns the transformation from fetched HTML or cached markdown into
normalized result objects used by the REST and MCP surfaces. It is intentionally
narrow: it understands extraction economics and output envelopes, but it does not
own routing, protocol transport, or persistence.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "build_cache_economics",
    "build_mcp_envelope",
    "build_response_provenance",
    "build_rest_response",
    "compute_saved_tokens",
]


def __getattr__(name: str) -> Any:
    """Lazily resolve extraction helpers to avoid import cycles during startup."""
    if name == "build_cache_economics":
        from .cache import build_cache_economics

        return build_cache_economics
    if name == "compute_saved_tokens":
        from .cache import compute_saved_tokens

        return compute_saved_tokens
    if name in {"build_mcp_envelope", "build_rest_response", "build_response_provenance"}:
        from .response import (
            build_mcp_envelope,
            build_response_provenance,
            build_rest_response,
        )

        return {
            "build_mcp_envelope": build_mcp_envelope,
            "build_rest_response": build_rest_response,
            "build_response_provenance": build_response_provenance,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
