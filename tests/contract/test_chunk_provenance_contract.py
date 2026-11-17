"""Contract tests for first-class chunk provenance."""

from dataclasses import asdict

from bintu_api.extraction.context import (
    attach_chunk_provenance,
    split_into_chunks,
)
from bintu_api.extraction.rag_chunking import split_semantic_chunks

PROVENANCE = {
    "source_url": "https://example.com/source",
    "final_url": "https://example.com/final",
    "content_sha256": "0" * 64,
    "extracted_at": "2026-01-01T00:00:00+00:00",
}


def _assert_chunk_provenance(chunk):
    assert chunk["source_url"] == PROVENANCE["source_url"]
    assert chunk["final_url"] == PROVENANCE["final_url"]
    assert chunk["content_sha256"] == PROVENANCE["content_sha256"]
    assert chunk["extracted_at"] == PROVENANCE["extracted_at"]


def test_sequential_chunks_carry_core_provenance():
    chunk_strings = split_into_chunks(
        "First paragraph.\n\nSecond paragraph.",
        20,
    )
    chunks = [
        {
            "index": index,
            "text": text,
            "approx_tokens": len(text) // 4,
            "tokens": len(text) // 4,
        }
        for index, text in enumerate(chunk_strings)
    ]

    enriched = attach_chunk_provenance(chunks, **PROVENANCE)

    assert len(enriched) > 0
    for chunk in enriched:
        _assert_chunk_provenance(chunk)


def test_semantic_chunks_carry_core_provenance():
    semantic_chunks = split_semantic_chunks(
        "# Heading\n\nFirst paragraph.\n\n## Subheading\n\nSecond paragraph.",
        max_tokens=20,
        source_url=PROVENANCE["source_url"],
        final_url=PROVENANCE["final_url"],
        content_sha256=PROVENANCE["content_sha256"],
        extracted_at=PROVENANCE["extracted_at"],
    )
    chunks = [asdict(chunk) for chunk in semantic_chunks]

    enriched = attach_chunk_provenance(chunks, **PROVENANCE)

    assert len(enriched) > 0
    for chunk in enriched:
        _assert_chunk_provenance(chunk)
