"""Contract tests for selected_sections response-envelope behavior."""

from bintu_api.context import ContextResult
from bintu_api.extraction.response import build_mcp_envelope, build_rest_response


def make_context(selected_sections=None):
    return ContextResult(
        mode="scrape",
        text="Alpha body",
        approx_tokens=3,
        html_tokens=10,
        token_method="ceil(characters/4)",
        limiting_factor="none",
        selected_sections=selected_sections,
    )


def test_mcp_envelope_includes_selected_sections_when_present():
    context = make_context(
        selected_sections=[
            {
                "heading": "Alpha",
                "level": 1,
                "index": 0,
                "text": "Alpha body",
            }
        ]
    )

    envelope = build_mcp_envelope(context, "https://example.com")

    assert envelope["selected_sections"] == context.selected_sections


def test_mcp_envelope_omits_selected_sections_when_absent():
    context = make_context(selected_sections=None)

    envelope = build_mcp_envelope(context, "https://example.com")

    assert "selected_sections" not in envelope


def test_rest_response_includes_selected_sections_when_present():
    context = make_context(
        selected_sections=[
            {
                "heading": "Alpha",
                "level": 1,
                "index": 0,
                "text": "Alpha body",
            }
        ]
    )

    response = build_rest_response(context, "https://example.com")

    assert response["selected_sections"] == context.selected_sections


def test_rest_response_omits_selected_sections_when_absent():
    context = make_context(selected_sections=None)

    response = build_rest_response(context, "https://example.com")

    assert "selected_sections" not in response