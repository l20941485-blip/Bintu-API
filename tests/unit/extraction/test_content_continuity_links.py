from bintu_api.extraction.chunker import _keep_lead_ins


def test_heading_continuity_in_chunks():
    """A heading that ends a chunk moves to the next chunk when it fits."""
    chunks = [
        "First chunk body.\n# Next Heading",
        "Next chunk body.",
    ]

    result = _keep_lead_ins(chunks, max_tokens=20)

    assert result[0] == "First chunk body."
    assert result[1] == "# Next Heading\nNext chunk body."


from bintu_api.extraction.context import ContextResult
from bintu_api.extraction.response import build_mcp_envelope


def test_mcp_envelope_preserves_source_url_with_sections():
    """Source URL remains in MCP provenance when sections are selected."""
    context = ContextResult(
        mode="scrape",
        text="Alpha body",
        approx_tokens=3,
        html_tokens=10,
        token_method="ceil(characters/4)",
        limiting_factor="none",
        selected_sections=[
            {
                "heading": "Alpha",
                "level": 1,
                "index": 0,
                "text": "Alpha body",
            }
        ],
    )

    envelope = build_mcp_envelope(context, "https://example.com")

    assert envelope["source_url"] == "https://example.com"
    assert envelope["selected_sections"] == context.selected_sections
