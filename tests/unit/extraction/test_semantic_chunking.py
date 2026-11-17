import pytest

from bintu_api.extraction.rag_chunking import (
    make_chunk_id,
    split_semantic_chunks,
)


def test_semantic_chunks_prefer_heading_boundaries():
    markdown = """# Guide

Intro text.

## Authentication

Use an API key.

## Rate limits

Requests are limited.
"""

    chunks = split_semantic_chunks(markdown, max_tokens=100)

    assert len(chunks) == 3
    assert chunks[0].text.startswith("# Guide")
    assert chunks[1].text.startswith("## Authentication")
    assert chunks[2].text.startswith("## Rate limits")


def test_semantic_chunks_include_heading_path():
    markdown = """# Bintu API

## Authentication

Use an API key.
"""

    chunks = split_semantic_chunks(markdown, max_tokens=100)

    assert chunks[1].heading_path == ["Bintu API", "Authentication"]


def test_chunk_id_is_deterministic():
    first = make_chunk_id(
        source_url="https://example.com/docs",
        content_sha256="abc",
        chunk_strategy="semantic",
        chunk_index=0,
    )

    second = make_chunk_id(
        source_url="https://example.com/docs",
        content_sha256="abc",
        chunk_strategy="semantic",
        chunk_index=0,
    )

    assert first == second
    assert first.startswith("sha256:")


def test_overlap_must_be_less_than_budget():
    with pytest.raises(ValueError):
        split_semantic_chunks(
            "text",
            max_tokens=100,
            overlap_tokens=100,
        )


def test_empty_text_returns_no_chunks():
    assert split_semantic_chunks("", max_tokens=100) == []
    assert split_semantic_chunks("   \n  ", max_tokens=100) == []
