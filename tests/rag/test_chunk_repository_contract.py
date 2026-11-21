"""Contract tests for the retrieval-ready RAG chunk repository."""

from __future__ import annotations

import hashlib
import unittest

from bintu_api.rag.models import Document, DocumentRevision, RagChunk
from bintu_api.rag.repositories import InMemoryChunkRepository


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_document() -> Document:
    return Document(
        document_id="doc_1",
        tenant_id="tenant_1",
        canonical_url="https://example.com/docs",
        title="Example Documentation",
    )


def make_revision(content_sha256: str) -> DocumentRevision:
    return DocumentRevision(
        revision_id=None,
        document_id="doc_1",
        source_url="https://example.com/original",
        final_url="https://example.com/final",
        content_sha256=content_sha256,
        content_fingerprint="sha256:content-fingerprint",
        extracted_at="2026-11-21T00:00:00+00:00",
        language="en",
    )


def make_chunks(content_sha256: str) -> list[RagChunk]:
    return [
        RagChunk(
            chunk_id=None,
            revision_id=None,
            document_id=None,
            tenant_id="tenant_1",
            chunk_index=index,
            chunk_strategy="semantic",
            text=text,
            chunk_sha256=None,
            heading_path=("Guide",),
            section_path="guide",
            char_start=index * 100,
            char_end=index * 100 + len(text),
            source_url="https://example.com/original",
            final_url="https://example.com/final",
            content_sha256=content_sha256,
            content_fingerprint="sha256:content-fingerprint",
            extracted_at="2026-11-21T00:00:00+00:00",
            access_labels=("public",),
        )
        for index, text in enumerate(
            (
                "# Guide\n\nIntroduction.",
                "## Authentication\n\nUse an API key.",
            )
        )
    ]


class ChunkRepositoryContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = InMemoryChunkRepository()
        self.document = make_document()
        self.revision = make_revision("sha256:content")
        self.chunks = make_chunks("sha256:content")

    def test_ingest_revision_persists_complete_provenance(self) -> None:
        result = self.repository.ingest_revision(
            self.document,
            self.revision,
            self.chunks,
        )

        self.assertIsNotNone(result.revision_id)
        self.assertEqual(len(result.chunks), 2)

        for index, chunk in enumerate(result.chunks):
            self.assertEqual(chunk.document_id, "doc_1")
            self.assertEqual(chunk.revision_id, result.revision_id)
            self.assertEqual(chunk.tenant_id, "tenant_1")
            self.assertEqual(chunk.chunk_index, index)
            self.assertEqual(chunk.source_url, "https://example.com/original")
            self.assertEqual(chunk.final_url, "https://example.com/final")
            self.assertEqual(chunk.content_sha256, "sha256:content")
            self.assertEqual(chunk.access_labels, ("public",))
            self.assertTrue(chunk.chunk_id.startswith("sha256:"))
            self.assertEqual(chunk.chunk_sha256, sha256(chunk.text))

    def test_identical_revision_is_idempotent(self) -> None:
        first = self.repository.ingest_revision(
            self.document,
            self.revision,
            self.chunks,
        )
        second = self.repository.ingest_revision(
            self.document,
            self.revision,
            self.chunks,
        )

        self.assertEqual(first.revision_id, second.revision_id)
        self.assertEqual(
            [chunk.chunk_id for chunk in first.chunks],
            [chunk.chunk_id for chunk in second.chunks],
        )

    def test_changed_content_creates_new_revision(self) -> None:
        first = self.repository.ingest_revision(
            self.document,
            self.revision,
            self.chunks,
        )

        changed = self.repository.ingest_revision(
            self.document,
            make_revision("sha256:changed-content"),
            make_chunks("sha256:changed-content"),
        )

        self.assertNotEqual(first.revision_id, changed.revision_id)
        self.assertNotEqual(
            [chunk.chunk_id for chunk in first.chunks],
            [chunk.chunk_id for chunk in changed.chunks],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
