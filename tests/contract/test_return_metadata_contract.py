"""Contract tests for the optional return_metadata chunk control."""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from bintu_api.extraction.context import extract_context


def _settings() -> SimpleNamespace:
    return SimpleNamespace(service_version="test")


def _chunk_context(*, return_metadata: bool):
    return asyncio.run(
        extract_context(
            request=MagicMock(),
            url="https://example.com/page",
            mode="chunk",
            max_tokens=100,
            chunk_strategy="semantic",
            identity="test-identity",
            raw_text=(
                "# Heading\n\nFirst paragraph.\n\nSecond paragraph."
            ),
            html_source_text="<html><body><p>Example</p></body></html>",
            extracted_at="2026-01-01T00:00:00+00:00",
            settings=_settings(),
            return_metadata=return_metadata,
        )
    )


def test_return_metadata_default_preserves_optional_enrichment():
    context = _chunk_context(return_metadata=True)

    assert context.chunks
    assert all("contains_code" in chunk for chunk in context.chunks)
    assert all("contains_table" in chunk for chunk in context.chunks)
    assert all("contains_links" in chunk for chunk in context.chunks)
    assert all("link_count" in chunk for chunk in context.chunks)
    assert all("page_title" in chunk for chunk in context.chunks)
    assert all("content_fingerprint" in chunk for chunk in context.chunks)


def test_return_metadata_false_removes_only_optional_enrichment():
    context = _chunk_context(return_metadata=False)

    assert context.chunks

    for chunk in context.chunks:
        assert "contains_code" not in chunk
        assert "contains_table" not in chunk
        assert "contains_links" not in chunk
        assert "link_count" not in chunk
        assert "page_title" not in chunk
        assert "content_fingerprint" not in chunk

        # Core identity and provenance remain available.
        assert chunk["chunk_id"].startswith("sha256:")
        assert chunk["source_url"]
        assert chunk["content_sha256"]
        assert chunk["extracted_at"] == "2026-01-01T00:00:00+00:00"


def _chunk_context_with_controls(
    *,
    include_heading_path: bool = True,
    include_page_context: bool = True,
):
    return asyncio.run(
        extract_context(
            request=MagicMock(),
            url="https://example.com/page",
            mode="chunk",
            max_tokens=100,
            chunk_strategy="semantic",
            identity="test-identity",
            raw_text=(
                "# Heading\n\nFirst paragraph.\n\nSecond paragraph."
            ),
            html_source_text="<html><body><p>Example</p></body></html>",
            extracted_at="2026-01-01T00:00:00+00:00",
            settings=_settings(),
            include_heading_path=include_heading_path,
            include_page_context=include_page_context,
        )
    )


def test_include_heading_path_false_removes_only_heading_path():
    context = _chunk_context_with_controls(include_heading_path=False)

    assert context.chunks
    for chunk in context.chunks:
        assert "heading_path" not in chunk
        assert "content_sha256" in chunk
        assert "extracted_at" in chunk


def test_include_page_context_true_adds_deterministic_context():
    context = _chunk_context_with_controls(include_page_context=True)

    assert context.chunks
    for chunk in context.chunks:
        assert isinstance(chunk["page_context"], str)
        assert chunk["page_context"]
        assert "content_sha256" in chunk
        assert "extracted_at" in chunk


def test_include_page_context_false_removes_only_page_context():
    context = _chunk_context_with_controls(include_page_context=False)

    assert context.chunks
    for chunk in context.chunks:
        assert "page_context" not in chunk
        assert "content_sha256" in chunk
        assert "extracted_at" in chunk
