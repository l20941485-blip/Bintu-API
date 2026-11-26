import pytest
from pydantic import ValidationError

from bintu_api.mcp.schemas import TOOL_INPUT_SCHEMA, TOOL_OUTPUT_SCHEMA
from bintu_api.mcp.tools import ToolArguments


def test_tool_input_schema_accepts_chunk_strategy_and_overlap():
    properties = TOOL_INPUT_SCHEMA["properties"]

    assert properties["chunk_strategy"]["enum"] == ["sequential", "semantic"]
    assert properties["chunk_strategy"]["default"] == "sequential"
    assert properties["overlap_tokens"]["minimum"] == 0
    assert properties["overlap_tokens"]["default"] == 0
    assert "chunk_strategy" not in TOOL_INPUT_SCHEMA["required"]
    assert "overlap_tokens" not in TOOL_INPUT_SCHEMA["required"]


def test_tool_output_schema_declares_limiting_factor_enum():
    limiting_factor = TOOL_OUTPUT_SCHEMA["properties"]["limiting_factor"]
    assert limiting_factor["type"] == "string"
    assert limiting_factor["enum"] == ["char_cap", "token_budget", "none"]


def test_tool_arguments_rejects_out_of_range_max_tokens() -> None:
    for invalid_max in (99, 50001):
        with pytest.raises(ValidationError):
            ToolArguments(url="https://example.com", max_tokens=invalid_max)


def test_tool_arguments_rejects_negative_or_excessive_overlap_tokens() -> None:
    with pytest.raises(ValidationError):
        ToolArguments(url="https://example.com", max_tokens=500, overlap_tokens=-1)

    for invalid_overlap in (500, 600):
        with pytest.raises(ValidationError, match="overlap_tokens must be less than max_tokens"):
            ToolArguments(
                url="https://example.com",
                max_tokens=500,
                overlap_tokens=invalid_overlap,
            )
