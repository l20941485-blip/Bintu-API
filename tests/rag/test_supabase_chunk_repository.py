"""Tests for the Supabase-backed RAG chunk repository adapter."""

from __future__ import annotations

import hashlib
import unittest
from unittest.mock import AsyncMock, Mock

from bintu_api.extraction.rag_chunking import make_chunk_id
from bintu_api.rag.models import Document, DocumentRevision, RagChunk
from bintu_api.rag.supabase import SupabaseChunkRepository


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_document() -> Document:
    return Document(
        document_id="doc_1",
        canonical_url="https://example.com/docs",
        title="Example Documentation",
        owner_identity=None,
    )


def make_revision() -> DocumentRevision:
    return DocumentRevision(
        revision_id=None,
        document_id="doc_1",
        source_url="https://example.com/original",
        final_url="https://example.com/final",
        content_sha256="sha256:content",
        content_fingerprint="sha256:content-fingerprint",
        extracted_at="2026-11-21T00:00:00+00:00",
        language="en",
    )


def make_chunks() -> list[RagChunk]:
    return [
        RagChunk(
            chunk_id=None,
            revision_id=None,
            document_id=None,
            owner_identity=None,
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
            content_sha256="sha256:content",
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


def expected_chunk_payload(chunk: RagChunk) -> dict:
    chunk_sha256 = sha256(chunk.text)
    chunk_id = make_chunk_id(
        source_url=chunk.source_url,
        content_sha256=chunk.content_sha256,
        chunk_strategy=chunk.chunk_strategy,
        chunk_index=chunk.chunk_index,
    )
    return {
        "chunk_id": chunk_id,
        "chunk_index": chunk.chunk_index,
        "chunk_strategy": chunk.chunk_strategy,
        "text": chunk.text,
        "chunk_sha256": chunk_sha256,
        "heading_path": ["Guide"],
        "section_path": "guide",
        "char_start": chunk.char_start,
        "char_end": chunk.char_end,
        "source_url": chunk.source_url,
        "final_url": chunk.final_url,
        "content_sha256": chunk.content_sha256,
        "content_fingerprint": chunk.content_fingerprint,
        "extracted_at": chunk.extracted_at,
        "access_labels": ["public"],
    }


class SupabaseChunkRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_ingest_revision_calls_ingest_rpc(self) -> None:
        chunks = make_chunks()
        response_data = {
            "document_id": "document_1",
            "revision_id": "revision_1",
            "chunks": [
                {
                    "chunk_id": expected_chunk_payload(chunk)["chunk_id"],
                    "chunk_sha256": sha256(chunk.text),
                    "chunk_index": chunk.chunk_index,
                }
                for chunk in chunks
            ],
        }

        supabase = Mock()
        supabase.rpc = Mock(
            return_value=Mock(
                execute=AsyncMock(
                    return_value=Mock(data=response_data)
                )
            )
        )

        repository = SupabaseChunkRepository(supabase)
        result = await repository.ingest_revision(
            make_document(),
            make_revision(),
            chunks,
        )

        supabase.rpc.assert_called_once_with(
            "ingest_rag_revision",
            {
                "p_document": {
                    "canonical_url": "https://example.com/docs",
                    "title": "Example Documentation",
                    "source_type": "web",
                    "owner_identity": None,
                },
                "p_revision": {
                    "source_url": "https://example.com/original",
                    "final_url": "https://example.com/final",
                    "content_sha256": "sha256:content",
                    "content_fingerprint": "sha256:content-fingerprint",
                    "extracted_at": "2026-11-21T00:00:00+00:00",
                    "language": "en",
                    "status": "active",
                },
                "p_chunks": [
                    expected_chunk_payload(chunk) for chunk in chunks
                ],
            },
        )

        self.assertEqual(result.revision_id, "revision_1")
        self.assertEqual(len(result.chunks), 2)

        for index, chunk in enumerate(result.chunks):
            expected = expected_chunk_payload(chunks[index])
            self.assertEqual(chunk.chunk_id, expected["chunk_id"])
            self.assertEqual(chunk.chunk_sha256, expected["chunk_sha256"])
            self.assertEqual(chunk.revision_id, "revision_1")
            self.assertEqual(chunk.document_id, "document_1")
            self.assertIsNone(chunk.owner_identity)


if __name__ == "__main__":
    unittest.main(verbosity=2)
