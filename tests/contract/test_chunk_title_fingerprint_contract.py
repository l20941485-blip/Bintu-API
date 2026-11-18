"""Contract tests for page title and content fingerprint provenance."""

from bintu_api.extraction.context import attach_chunk_provenance

PROVENANCE = {
    "source_url": "https://example.com/source",
    "final_url": "https://example.com/final",
    "content_sha256": "0" * 64,
    "extracted_at": "2026-01-01T00:00:00+00:00",
    "page_title": "Example Page",
    "content_fingerprint": "sha256:" + "1" * 64,
}


def test_chunks_include_title_and_fingerprint():
    chunks = [
        {"index": 0, "text": "First chunk", "approx_tokens": 3, "tokens": 3},
        {"index": 1, "text": "Second chunk", "approx_tokens": 3, "tokens": 3},
    ]

    enriched = attach_chunk_provenance(chunks, **PROVENANCE)

    assert len(enriched) == 2
    for chunk in enriched:
        assert chunk["page_title"] == "Example Page"
        assert chunk["content_fingerprint"].startswith("sha256:")
