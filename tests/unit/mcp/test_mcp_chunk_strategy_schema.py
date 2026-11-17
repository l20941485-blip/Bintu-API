from bintu_api.mcp.schemas import TOOL_INPUT_SCHEMA


def test_tool_input_schema_accepts_chunk_strategy_and_overlap():
    properties = TOOL_INPUT_SCHEMA["properties"]

    assert properties["chunk_strategy"]["enum"] == ["sequential", "semantic"]
    assert properties["chunk_strategy"]["default"] == "sequential"
    assert properties["overlap_tokens"]["minimum"] == 0
    assert properties["overlap_tokens"]["default"] == 0
    assert "chunk_strategy" not in TOOL_INPUT_SCHEMA["required"]
    assert "overlap_tokens" not in TOOL_INPUT_SCHEMA["required"]
