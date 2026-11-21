"""Contract tests for grounded RAG answer generation."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock

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
    *,
    heading_path: tuple[str, ...] = ("Guide",),
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        revision_id="revision-1",
        document_id="document-1",
        text=text,
        score=score,
        source_url="https://example.com/original",
        final_url="https://example.com/final",
        heading_path=heading_path,
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
                    heading_path=("Guide", "Authentication"),
                )
            ]
        )
        service = RagAnswerService(RagRetrievalService(repository))

        result = await service.answer(query="How do I authenticate?")

        self.assertFalse(result.insufficient_evidence)
        self.assertEqual(result.answer, "Use an API key.")
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0].chunk_id, "chunk-auth")
        self.assertEqual(
            result.citations[0].source_url,
            "https://example.com/original",
        )

    async def test_combines_evidence_from_multiple_chunks(self) -> None:
        repository = FakeAnswerRepository(
            [
                make_chunk(
                    "chunk-auth",
                    "## Authentication\n\nUse an API key.",
                    1.0,
                    heading_path=("Guide", "Authentication"),
                ),
                make_chunk(
                    "chunk-rate-limits",
                    "## Rate limits\n\nRequests are limited to 100 per minute.",
                    0.8,
                    heading_path=("Guide", "Rate limits"),
                ),
            ]
        )
        service = RagAnswerService(RagRetrievalService(repository))

        result = await service.answer(
            query="How do I use authentication and what are the rate limits?"
        )

        self.assertFalse(result.insufficient_evidence)
        self.assertEqual(
            result.answer,
            "Use an API key. Requests are limited to 100 per minute.",
        )
        self.assertEqual(
            [citation.chunk_id for citation in result.citations],
            ["chunk-auth", "chunk-rate-limits"],
        )

    async def test_excludes_irrelevant_evidence(self) -> None:
        repository = FakeAnswerRepository(
            [
                make_chunk(
                    "chunk-introduction",
                    "## Introduction\n\nThis guide explains the product.",
                    0.9,
                    heading_path=("Guide", "Introduction"),
                ),
                make_chunk(
                    "chunk-auth",
                    "## Authentication\n\nUse an API key.",
                    0.8,
                    heading_path=("Guide", "Authentication"),
                ),
            ]
        )
        service = RagAnswerService(RagRetrievalService(repository))

        result = await service.answer(query="How do I authenticate?")

        self.assertEqual(result.answer, "Use an API key.")
        self.assertEqual(
            [citation.chunk_id for citation in result.citations],
            ["chunk-auth"],
        )

    async def test_does_not_duplicate_identical_evidence(self) -> None:
        repository = FakeAnswerRepository(
            [
                make_chunk(
                    "chunk-auth",
                    "## Authentication\n\nUse an API key.",
                    1.0,
                    heading_path=("Guide", "Authentication"),
                ),
                make_chunk(
                    "chunk-auth-duplicate",
                    "## Authentication\n\nUse an API key.",
                    0.9,
                    heading_path=("Guide", "Authentication"),
                ),
            ]
        )
        service = RagAnswerService(RagRetrievalService(repository))

        result = await service.answer(query="How do I use authentication?")

        self.assertEqual(result.answer, "Use an API key.")
        self.assertEqual(
            [citation.chunk_id for citation in result.citations],
            ["chunk-auth"],
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


class OwnerIdentityAnswerRepository:
    def __init__(self) -> None:
        self.search_chunks = AsyncMock(return_value=[])


class RagOwnerIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_passes_owner_identity_to_repository(self) -> None:
        repository = OwnerIdentityAnswerRepository()
        service = RagAnswerService(RagRetrievalService(repository))

        await service.answer(
            query="How do I use authentication?",
            access_labels=("public",),
            owner_identity="user-1",
        )

        repository.search_chunks.assert_awaited_once_with(
            query="How do I use authentication?",
            limit=5,
            access_labels=("public",),
            owner_identity="user-1",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
