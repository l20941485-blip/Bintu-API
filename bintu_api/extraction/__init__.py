"""Extraction orchestration and response-shaping helpers.

This package owns the transformation from fetched HTML or cached markdown into
normalized result objects used by the REST and MCP surfaces. It is intentionally
narrow: it understands extraction economics and output envelopes, but it does not
own routing, protocol transport, or persistence.
"""

from .response import build_mcp_envelope, build_rest_response, build_response_provenance

__all__ = [
    "build_mcp_envelope",
    "build_response_provenance",
    "build_rest_response",
]
