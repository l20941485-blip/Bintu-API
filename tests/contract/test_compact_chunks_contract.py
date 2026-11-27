"""Contract tests for opt-in compact_chunks payload slimming."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from bintu_api.extraction.context import extract_context


def _settings() -> SimpleNamespace:
    return SimpleNamespace(service_version="test")


def _run_extract(*, compact_chunks: bool):
    return asyncio.run(
        extract_context(
            request=MagicMock(),
            url="https://example.com/very-long-path/documentation/guide",
            mode="chunk",
            max_tokens=100,
            chunk_strategy="semantic",
            identity="test-identity",
            raw_text=(
                "# Architecture Overview\n\n"
                "First paragraph with detail.\n\n"
                "## Second Section\n\n"
                "Second paragraph with detail."
            ),
            html_source_text="<html><body><p>Example</p></body></html>",
            extracted_at="2026-11-27T13:00:00+00:00",
            settings=_settings(),
            compact_chunks=compact_chunks,
        )
    )


def test_compact_chunks_false_preserves_provenance():
    full_ctx = _run_extract(compact_chunks=False)
    assert full_ctx.chunks
    first = full_ctx.chunks[0]
    assert first["source_url"]
    assert first["content_sha256"]
    assert first["extracted_at"]
    assert first["chunk_id"].startswith("sha256:")
    assert first["chunk_sha256"]


def test_compact_chunks_true_reduces_payload_and_keeps_identity():
    full_ctx = _run_extract(compact_chunks=False)
    compact_ctx = _run_extract(compact_chunks=True)

    assert len(compact_ctx.chunks) == len(full_ctx.chunks)

    for full_chunk, compact_chunk in zip(full_ctx.chunks, compact_ctx.chunks, strict=True):
        assert compact_chunk["chunk_id"] == full_chunk["chunk_id"]
        assert compact_chunk["chunk_sha256"] == full_chunk["chunk_sha256"]
        assert compact_chunk["text"] == full_chunk["text"]

        for stripped_key in (
            "source_url",
            "final_url",
            "content_sha256",
            "extracted_at",
            "page_context",
        ):
            assert stripped_key not in compact_chunk

        assert len(json.dumps(compact_chunk)) < len(json.dumps(full_chunk))
