"""Tests for MCP section-selector validation."""

import pytest
from pydantic import ValidationError

from bintu_api.mcp.tools import ToolArguments


def make_arguments(sections):
    return ToolArguments.model_validate(
        {
            "url": "https://example.com",
            "sections": sections,
        }
    )


def test_accepts_newline_separated_string():
    arguments = make_arguments("Alpha\nBeta")

    assert arguments.sections == ["Alpha", "Beta"]


def test_accepts_array_of_strings():
    arguments = make_arguments(["Alpha", "Beta"])

    assert arguments.sections == ["Alpha", "Beta"]


def test_rejects_whitespace_only_string():
    with pytest.raises(ValidationError):
        make_arguments("   \n  ")


def test_rejects_whitespace_only_array_entry():
    with pytest.raises(ValidationError):
        make_arguments(["Alpha", "   "])


def test_rejects_selector_over_200_characters():
    with pytest.raises(ValidationError):
        make_arguments(["a" * 201])


def test_accepts_selector_exactly_200_characters():
    arguments = make_arguments(["a" * 200])

    assert arguments.sections == ["a" * 200]

