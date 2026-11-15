from bintu_api.extraction.context import ContextResult
from bintu_api.extraction.response import build_mcp_envelope


def _context(mode: str, text: str, chunks: list[dict[str, object]]) -> ContextResult:
    return ContextResult(
        mode=mode,
        text=text,
        approx_tokens=10,
        html_tokens=100,
        token_method="ceil(characters/4)",
        limiting_factor="none",
        chunk_count=len(chunks),
        chunks=chunks,
        source_url="https://example.com",
        extracted_at="2026-01-01T00:00:00Z",
    )


def test_chunk_mode_does_not_duplicate_document_in_text():
    chunks = [
        {"index": 0, "text": "Chunk one", "approx_tokens": 3, "tokens": 3},
        {"index": 1, "text": "Chunk two", "approx_tokens": 3, "tokens": 3},
    ]
    context = _context(
        "chunk",
        "Chunk one\n\n---\n\nChunk two",
        chunks,
    )

    envelope = build_mcp_envelope(context, "https://example.com")

    assert envelope["text"] == ""
    assert envelope["chunks"] == chunks


def test_scrape_mode_preserves_text():
    context = _context("scrape", "Selected text", [])
    envelope = build_mcp_envelope(context, "https://example.com")

    assert envelope["text"] == "Selected text"
    assert envelope["chunks"] == []
