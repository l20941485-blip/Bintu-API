from bintu_api.mcp.schemas import TOOL_INPUT_SCHEMA


def test_tool_input_schema_accepts_chunk_strategy_and_overlap():
    properties = TOOL_INPUT_SCHEMA["properties"]

    assert properties["chunk_strategy"]["enum"] == ["sequential", "semantic"]
    assert properties["chunk_strategy"]["default"] == "sequential"
    assert properties["overlap_tokens"]["minimum"] == 0
    assert properties["overlap_tokens"]["default"] == 0
    assert "chunk_strategy" not in TOOL_INPUT_SCHEMA["required"]
    assert "overlap_tokens" not in TOOL_INPUT_SCHEMA["required"]


def test_tool_output_schema_declares_limiting_factor_enum():
    from bintu_api.mcp.schemas import TOOL_OUTPUT_SCHEMA

    limiting_factor = TOOL_OUTPUT_SCHEMA["properties"]["limiting_factor"]
    assert limiting_factor["type"] == "string"
    assert limiting_factor["enum"] == ["char_cap", "token_budget", "none"]
