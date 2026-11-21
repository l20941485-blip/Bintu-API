"""Contract tests for keyword retrieval over RAG chunks."""

from __future__ import annotations

import unittest

from bintu_api.rag.retrieval import RagRetrievalService, RetrievedChunk


class RagRetrievalServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_returns_ranked_chunks(self) -> None:
        repository = FakeRetrievalRepository()
        service = RagRetrievalService(repository)

        results = await service.search(
            query="guide authentication",
            limit=2,
            access_labels=("public",),
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].chunk_id, "chunk-auth")
        self.assertEqual(results[0].score, 1.0)
        self.assertEqual(results[1].chunk_id, "chunk-guide")
        self.assertEqual(results[1].score, 0.5)

    async def test_search_filters_by_access_labels(self) -> None:
        repository = FakeRetrievalRepository()
        service = RagRetrievalService(repository)

        results = await service.search(
            query="authentication",
            limit=10,
            access_labels=("public",),
        )

        self.assertEqual([result.chunk_id for result in results], ["chunk-auth"])

    async def test_search_rejects_blank_query(self) -> None:
        service = RagRetrievalService(FakeRetrievalRepository())

        with self.assertRaises(ValueError):
            await service.search(query="   ")

    async def test_search_returns_private_chunks_only_to_owner(self) -> None:
        repository = FakeRetrievalRepository()
        service = RagRetrievalService(repository)

        owner_results = await service.search(
            query="authentication",
            limit=10,
            owner_identity="user-1",
        )

        self.assertIn("chunk-private", [result.chunk_id for result in owner_results])

        other_results = await service.search(
            query="authentication",
            limit=10,
            owner_identity="user-2",
        )

        self.assertNotIn(
            "chunk-private",
            [result.chunk_id for result in other_results],
        )

    async def test_search_hides_private_chunks_from_anonymous_callers(self) -> None:
        repository = FakeRetrievalRepository()
        service = RagRetrievalService(repository)

        results = await service.search(
            query="authentication",
            limit=10,
        )

        self.assertNotIn(
            "chunk-private",
            [result.chunk_id for result in results],
        )


class FakeRetrievalRepository:
    async def search_chunks(
        self,
        *,
        query: str,
        limit: int,
        access_labels: tuple[str, ...],
        owner_identity: str | None,
    ) -> list[RetrievedChunk]:
        candidates = [
            RetrievedChunk(
                chunk_id="chunk-guide",
                revision_id="revision-1",
                document_id="document-1",
                text="# Guide\n\nIntroduction.",
                score=0.5,
                source_url="https://example.com/original",
                final_url="https://example.com/final",
                heading_path=("Guide",),
                access_labels=("public",),
            ),
            RetrievedChunk(
                chunk_id="chunk-auth",
                revision_id="revision-1",
                document_id="document-1",
                text="## Authentication\n\nUse an API key.",
                score=1.0,
                source_url="https://example.com/original",
                final_url="https://example.com/final",
                heading_path=("Guide", "Authentication"),
                access_labels=("public",),
            ),
            RetrievedChunk(
                chunk_id="chunk-private",
                revision_id="revision-1",
                document_id="document-1",
                text="## Authentication\n\nPrivate internal material.",
                score=2.0,
                source_url="https://example.com/original",
                final_url="https://example.com/final",
                heading_path=("Guide", "Authentication"),
                access_labels=("private",),
            ),
        ]

        query_terms = {
            term
            for term in query.lower().split()
            if term
        }

        owners = {
            "chunk-private": "user-1",
        }

        filtered = [
            candidate
            for candidate in candidates
            if any(term in candidate.text.lower() for term in query_terms)
            and (
                not access_labels
                or any(label in candidate.access_labels for label in access_labels)
            )
            and (
                "private" not in candidate.access_labels
                or owner_identity == owners.get(candidate.chunk_id)
            )
        ]
        return sorted(filtered, key=lambda candidate: candidate.score, reverse=True)[:limit]


if __name__ == "__main__":
    unittest.main(verbosity=2)
