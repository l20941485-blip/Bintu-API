"""Contract tests for grounded RAG answer generation."""

from __future__ import annotations

import unittest

from bintu_api.rag.answer import RagAnswerService
from bintu_api.rag.retrieval import RagRetrievalService, RetrievedChunk


class FakeAnswerRepository:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks

    async def search_chunks(
        self,
        *,
        query: str,
        limit: int,
        access_labels: tuple[str, ...],
        owner_identity: str | None,
    ) -> list[RetrievedChunk]:
        return self._chunks[:limit]


def make_chunk(
    chunk_id: str,
    text: str,
    score: float,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        revision_id="revision-1",
        document_id="document-1",
        text=text,
        score=score,
        source_url="https://example.com/original",
        final_url="https://example.com/final",
        heading_path=("Guide",),
        access_labels=("public",),
    )


class RagAnswerServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_answers_from_retrieved_evidence(self) -> None:
        repository = FakeAnswerRepository(
            [
                make_chunk(
                    "chunk-auth",
                    "## Authentication\n\nUse an API key.",
                    1.0,
                )
            ]
        )
        service = RagAnswerService(RagRetrievalService(repository))

        result = await service.answer(query="How do I authenticate?")

        self.assertFalse(result.insufficient_evidence)
        self.assertEqual(
            result.answer,
            "Use an API key.",
        )
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0].chunk_id, "chunk-auth")
        self.assertEqual(
            result.citations[0].source_url,
            "https://example.com/original",
        )

    async def test_marks_insufficient_evidence_without_chunks(self) -> None:
        service = RagAnswerService(
            RagRetrievalService(FakeAnswerRepository([]))
        )

        result = await service.answer(query="How do I authenticate?")

        self.assertTrue(result.insufficient_evidence)
        self.assertEqual(result.answer, "")
        self.assertEqual(result.citations, ())

    async def test_rejects_blank_query(self) -> None:
        service = RagAnswerService(
            RagRetrievalService(FakeAnswerRepository([]))
        )

        with self.assertRaises(ValueError):
            await service.answer(query="   ")


if __name__ == "__main__":
    unittest.main(verbosity=2)
