"""Tests for the MCP section-selector schema documentation."""

from bintu_api.mcp.schemas import TOOL_INPUT_SCHEMA


def test_sections_schema_accepts_string_or_array():
    schema = TOOL_INPUT_SCHEMA["properties"]["sections"]

    assert "oneOf" in schema

    types = [option["type"] for option in schema["oneOf"]]

    assert "string" in types
    assert "array" in types

    array_option = next(
        option for option in schema["oneOf"] if option["type"] == "array"
    )
    assert array_option["items"] == {"type": "string"}


def test_sections_schema_documents_both_formats():
    description = TOOL_INPUT_SCHEMA["properties"]["sections"]["description"]

    assert "newline-separated string" in description
    assert "array of strings" in description
    assert "200" in description

