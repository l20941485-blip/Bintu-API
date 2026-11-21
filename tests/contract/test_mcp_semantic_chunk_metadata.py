"""MCP semantic chunking must expose the same retrieval metadata as REST."""

from bintu_api.extraction.context import ContextResult
from bintu_api.extraction.response import build_mcp_envelope


def test_mcp_semantic_chunk_metadata_contract():

    context = ContextResult(
        mode="chunk",
        text="",
        approx_tokens=10,
        html_tokens=100,
        token_method="ceil(characters/4)",
        limiting_factor="none",
        tokens=10,
        chunk_count=2,
        cache_hit=False,
        cache_layer="none",
        chunks=[
            {
                "index": 0,
                "text": "# Heading\n\nFirst semantic chunk.",
                "approx_tokens": 5,
                "tokens": 5,
                "chunk_strategy": "semantic",
                "chunk_id": "sha256:test",
                "heading_path": ["Heading"],
                "section_index": 0,
            },
            {
                "index": 1,
                "text": "## Subheading\n\nSecond semantic chunk.",
                "approx_tokens": 5,
                "tokens": 5,
                "chunk_strategy": "semantic",
                "chunk_id": "sha256:test-2",
                "heading_path": ["Heading", "Subheading"],
                "section_index": 1,
            },
        ],
        source_url="https://example.com",
        extracted_at="2026-01-01T00:00:00+00:00",
        split=True,
    )

    envelope = build_mcp_envelope(context, "https://example.com")

    assert envelope["chunk_count"] == 2
    assert envelope["split"] is True

    for chunk in envelope["chunks"]:
        assert chunk["chunk_strategy"] == "semantic"
        assert chunk["chunk_id"].startswith("sha256:")
        assert isinstance(chunk["heading_path"], list)
        assert isinstance(chunk["section_index"], int)
