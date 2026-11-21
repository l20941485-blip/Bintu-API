"""Tests for document-scoped RAG answers."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

from bintu_api.rag.answer import RagAnswerService
from bintu_api.rag.retrieval import RagRetrievalService, RetrievedChunk


class RecordingRepository:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks
        self.search_chunks = AsyncMock(return_value=self._chunks)


def make_chunk(document_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk-{document_id}",
        revision_id="revision-1",
        document_id=document_id,
        text="## Authentication\n\nUse an API key.",
        score=1.0,
        source_url="https://example.com/original",
        final_url="https://example.com/final",
        heading_path=("Guide", "Authentication"),
        access_labels=("public",),
    )


class DocumentScopedAnswerTests(unittest.IsolatedAsyncioTestCase):
    async def test_forwards_document_scope_to_repository(self) -> None:
        repository = RecordingRepository([make_chunk("document-1")])
        service = RagAnswerService(RagRetrievalService(repository))

        result = await service.answer(
            query="How do I authenticate?",
            owner_identity="user-1",
            document_id="document-1",
        )

        repository.search_chunks.assert_awaited_once_with(
            query="How do I authenticate?",
            limit=5,
            access_labels=(),
            owner_identity="user-1",
            document_id="document-1",
        )

        self.assertFalse(result.insufficient_evidence)
        self.assertEqual(result.answer, "Use an API key.")
        self.assertEqual(
            result.citations[0].document_id,
            "document-1",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
