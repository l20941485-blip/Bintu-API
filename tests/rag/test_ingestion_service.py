"""Tests for mapping extraction output into RAG ingestion."""

from __future__ import annotations

import hashlib
import unittest

from bintu_api.extraction.rag_chunking import split_semantic_chunks
from bintu_api.rag.ingestion import (
    ExtractionIngestionRequest,
    RagIngestionService,
)
from bintu_api.rag.models import IngestedRevision
from bintu_api.rag.repositories import InMemoryChunkRepository


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_request() -> ExtractionIngestionRequest:
    markdown = "# Guide\n\nIntroduction.\n\n## Authentication\n\nUse an API key."
    chunks = split_semantic_chunks(
        markdown,
        max_tokens=200,
        overlap_tokens=0,
        source_url="https://example.com/original",
        final_url="https://example.com/final",
        content_sha256="sha256:content",
        extracted_at="2026-11-21T00:00:00+00:00",
    )

    return ExtractionIngestionRequest(
        canonical_url="https://example.com/docs",
        title="Example Documentation",
        source_type="web",
        owner_identity=None,
        source_url="https://example.com/original",
        final_url="https://example.com/final",
        content_sha256="sha256:content",
        content_fingerprint="sha256:content-fingerprint",
        extracted_at="2026-11-21T00:00:00+00:00",
        language="en",
        status="active",
        chunks=chunks,
        access_labels=("public",),
    )


class RagIngestionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_maps_semantic_chunks_into_rag_chunks(self) -> None:
        repository = InMemoryChunkRepository()
        service = RagIngestionService(repository)
        request = make_request()

        result = await service.ingest(request)

        self.assertIsInstance(result, IngestedRevision)
        self.assertIsNotNone(result.revision_id)
        self.assertEqual(result.document.canonical_url, "https://example.com/docs")
        self.assertEqual(result.revision.content_sha256, "sha256:content")
        self.assertEqual(len(result.chunks), len(request.chunks))

        for source, persisted in zip(request.chunks, result.chunks, strict=True):
            self.assertEqual(persisted.chunk_id, source.chunk_id)
            self.assertEqual(persisted.chunk_index, source.index)
            self.assertEqual(persisted.chunk_strategy, source.chunk_strategy)
            self.assertEqual(persisted.text, source.text)
            self.assertEqual(persisted.chunk_sha256, sha256(source.text))
            self.assertEqual(persisted.heading_path, tuple(source.heading_path))
            self.assertEqual(persisted.source_url, source.source_url)
            self.assertEqual(persisted.final_url, source.final_url)
            self.assertEqual(persisted.content_sha256, request.content_sha256)
            self.assertEqual(persisted.extracted_at, source.extracted_at)
            self.assertEqual(persisted.access_labels, ("public",))
            self.assertIsNone(persisted.owner_identity)

    async def test_identical_extraction_is_idempotent(self) -> None:
        repository = InMemoryChunkRepository()
        service = RagIngestionService(repository)
        request = make_request()

        first = await service.ingest(request)
        second = await service.ingest(request)

        self.assertEqual(first.revision_id, second.revision_id)
        self.assertEqual(
            [chunk.chunk_id for chunk in first.chunks],
            [chunk.chunk_id for chunk in second.chunks],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
