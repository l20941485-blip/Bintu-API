"""Test Mcp Module Boundaries for Bintu.

This module owns a focused responsibility within the service and must remain isolated from unrelated transport or persistence concerns.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

from bintu_api import mcp
from bintu_api.mcp import http_api, protocol, schemas, tools


def test_http_api_uses_canonical_schemas_and_tool_models():
    assert http_api.TOOL_INPUT_SCHEMA is schemas.TOOL_INPUT_SCHEMA
    assert http_api.TOOL_OUTPUT_SCHEMA is schemas.TOOL_OUTPUT_SCHEMA
    assert http_api.ToolArguments is tools.ToolArguments
    assert http_api.ToolCallRequest is tools.ToolCallRequest
    assert mcp.ToolArguments is tools.ToolArguments


def test_streamable_protocol_envelopes_remain_canonical():
    assert protocol._rpc_result("request-1", {"ok": True}) == {
        "jsonrpc": "2.0",
        "id": "request-1",
        "result": {"ok": True},
    }
    assert protocol._rpc_error("request-1", -32600, "invalid request") == {
        "jsonrpc": "2.0",
        "id": "request-1",
        "error": {"code": -32600, "message": "invalid request"},
    }
    assert {"initialize", "tools/list", "ping"} == protocol.PUBLIC_MCP_METHODS


