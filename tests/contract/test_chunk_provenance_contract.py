"""Contract tests for first-class chunk provenance."""

import hashlib
from dataclasses import asdict

from bintu_api.extraction.chunk_location import (
    annotate_chunk_locations,
)
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
    assert chunk["chunk_id"].startswith("sha256:")
    assert len(chunk["chunk_id"]) == 71
    assert len(chunk["chunk_sha256"]) == 64
    expected_digest = hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest()
    assert chunk["chunk_sha256"] == expected_digest


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
    chunks = annotate_chunk_locations(
        chunks,
        source_text="First paragraph.\n\nSecond paragraph.",
    )

    enriched = attach_chunk_provenance(chunks, **PROVENANCE)

    assert len(enriched) > 0
    for chunk in enriched:
        _assert_chunk_provenance(chunk)

        assert "heading_path" in chunk
        assert "char_start" in chunk
        assert "char_end" in chunk
        assert "reassembled" in chunk

        assert chunk["reassembled"] is False
        assert chunk["char_start"] is not None
        assert chunk["char_end"] > chunk["char_start"]

    assert len({chunk["chunk_id"] for chunk in enriched}) == len(enriched)


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
    chunks = annotate_chunk_locations(
        chunks,
        source_text=(
            "# Heading\n\nFirst paragraph.\n\n"
            "## Subheading\n\nSecond paragraph."
        ),
    )

    enriched = attach_chunk_provenance(chunks, **PROVENANCE)

    assert len(enriched) > 0
    for chunk in enriched:
        _assert_chunk_provenance(chunk)

    assert len({chunk["chunk_id"] for chunk in enriched}) == len(enriched)

    assert len({chunk["chunk_id"] for chunk in enriched}) == len(enriched)

def test_chunk_location_marks_unlocatable_chunk_reassembled():
    chunks = [
        {
            "index": 0,
            "text": "Moved heading\n\nBody",
            "approx_tokens": 4,
            "tokens": 4,
        }
    ]

    annotated = annotate_chunk_locations(
        chunks,
        source_text="Different source text.",
    )

    assert annotated[0]["reassembled"] is True
    assert annotated[0]["char_start"] is None
    assert annotated[0]["char_end"] is None


def test_chunk_ids_are_stable_for_unchanged_content():
    source_text = (
        "# Heading\n\nFirst paragraph.\n\n"
        "## Subheading\n\nSecond paragraph."
    )

    def build_chunks():
        semantic_chunks = split_semantic_chunks(
            source_text,
            max_tokens=20,
            source_url=PROVENANCE["source_url"],
            final_url=PROVENANCE["final_url"],
            content_sha256=PROVENANCE["content_sha256"],
            extracted_at=PROVENANCE["extracted_at"],
        )
        chunks = [asdict(chunk) for chunk in semantic_chunks]
        chunks = annotate_chunk_locations(
            chunks,
            source_text=source_text,
        )
        return attach_chunk_provenance(chunks, **PROVENANCE)

    first = build_chunks()
    second = build_chunks()

    assert len(first) == len(second)

    for left, right in zip(first, second, strict=True):
        assert left["text"] == right["text"]
        assert left["chunk_id"] == right["chunk_id"]
        assert left["chunk_sha256"] == right["chunk_sha256"]
        assert left["char_start"] == right["char_start"]
        assert left["char_end"] == right["char_end"]


def test_chunk_provenance_includes_content_fingerprint():
    from bintu_api.extraction.fingerprint import compute_content_fingerprint

    markdown = "# Heading\n\nFirst paragraph.\n\n## Subheading\n\nSecond paragraph."
    fingerprint = compute_content_fingerprint(markdown)

    assert fingerprint.startswith("sha256:")
    assert fingerprint != "sha256:" + "0" * 64

def test_summarize_chunks_include_provenance():
    import asyncio
    import hashlib
    from types import SimpleNamespace

    from bintu_api.extraction.context import extract_context
    from bintu_api.extraction.fingerprint import compute_content_fingerprint

    raw_text = (
        "First sentence of the article for summary provenance.\n"
        "Second sentence adds extra detail so token budgeting truncates cleanly."
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(settings=SimpleNamespace())),
        state=SimpleNamespace(request_id="test-request"),
        headers={},
        client=SimpleNamespace(host="127.0.0.1"),
    )
    result = asyncio.run(
        extract_context(
            request=request,
            identity="contract-test",
            url="https://example.com/article?token=secret",
            mode="summarize",
            max_tokens=16,
            raw_text=raw_text,
            html_source_text="<html><head><title>Sample Title</title></head><body>" + raw_text + "</body></html>",
            extracted_at="2026-11-25T16:46:00+00:00",
        )
    )

    assert result.chunks is not None and len(result.chunks) == 1
    chunk = result.chunks[0]
    assert chunk["text"] == result.text
    assert chunk["approx_tokens"] == result.approx_tokens
    assert chunk["tokens"] == result.approx_tokens
    assert chunk["source_url"] == "https://example.com/article"
    assert chunk["final_url"] == "https://example.com/article"
    assert chunk["extracted_at"] == "2026-11-25T16:46:00+00:00"
    assert chunk["content_sha256"] == hashlib.sha256(result.text.encode("utf-8")).hexdigest()
    assert chunk["content_fingerprint"] == compute_content_fingerprint(result.text)
