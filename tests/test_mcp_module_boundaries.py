from bintu_api import mcp
from bintu_api.mcp import legacy, protocol, schemas, tools


def test_legacy_imports_use_canonical_schemas_and_tool_models():
    assert legacy.TOOL_INPUT_SCHEMA is schemas.TOOL_INPUT_SCHEMA
    assert legacy.TOOL_OUTPUT_SCHEMA is schemas.TOOL_OUTPUT_SCHEMA
    assert legacy.ToolArguments is tools.ToolArguments
    assert legacy.ToolCallRequest is tools.ToolCallRequest
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
