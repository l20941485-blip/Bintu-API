"""Tests for privacy-preserving RAG answer observability."""

from __future__ import annotations

import unittest

from bintu_api.rag.answer import RagAnswerService
from bintu_api.rag.observability import (
    LoggingRagAnswerObserver,
    RagAnswerObservability,
)
from bintu_api.rag.retrieval import RagRetrievalService, RetrievedChunk


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[RagAnswerObservability] = []

    def record_answer(
        self,
        event: RagAnswerObservability,
    ) -> None:
        self.events.append(event)


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
        document_id: str | None = None,
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
        heading_path=("Guide", "Authentication"),
        access_labels=("public",),
    )


class RagAnswerObservabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_successful_answer_metrics(self) -> None:
        observer = RecordingObserver()
        repository = FakeAnswerRepository(
            [
                make_chunk(
                    "chunk-auth",
                    "## Authentication\n\nUse an API key.",
                    1.0,
                )
            ]
        )
        service = RagAnswerService(
            RagRetrievalService(repository),
            observer=observer,
        )

        await service.answer(
            query="How do I authenticate?",
            access_labels=("public",),
            owner_identity="user-1",
        )

        self.assertEqual(len(observer.events), 1)
        event = observer.events[0]

        self.assertEqual(event.query_length, len("How do I authenticate?"))
        self.assertEqual(event.retrieved_chunk_count, 1)
        self.assertEqual(event.selected_evidence_count, 1)
        self.assertEqual(event.citation_count, 1)
        self.assertFalse(event.insufficient_evidence)
        self.assertGreaterEqual(event.latency_ms, 0)
        self.assertEqual(event.retrieved_chunk_ids, ("chunk-auth",))
        self.assertEqual(event.citation_chunk_ids, ("chunk-auth",))
        self.assertEqual(event.access_label_count, 1)
        self.assertTrue(event.has_owner_identity)

    async def test_records_insufficient_evidence_metrics(self) -> None:
        observer = RecordingObserver()
        service = RagAnswerService(
            RagRetrievalService(FakeAnswerRepository([])),
            observer=observer,
        )

        await service.answer(
            query="How do I authenticate?",
            access_labels=("public",),
        )

        self.assertEqual(len(observer.events), 1)
        event = observer.events[0]

        self.assertEqual(event.retrieved_chunk_count, 0)
        self.assertEqual(event.selected_evidence_count, 0)
        self.assertEqual(event.citation_count, 0)
        self.assertTrue(event.insufficient_evidence)
        self.assertEqual(event.retrieved_chunk_ids, ())
        self.assertEqual(event.citation_chunk_ids, ())
        self.assertFalse(event.has_owner_identity)

    async def test_does_not_record_query_or_chunk_content(self) -> None:
        observer = RecordingObserver()
        repository = FakeAnswerRepository(
            [
                make_chunk(
                    "chunk-auth",
                    "## Authentication\n\nUse an API key.",
                    1.0,
                )
            ]
        )
        service = RagAnswerService(
            RagRetrievalService(repository),
            observer=observer,
        )

        await service.answer(query="How do I authenticate?")

        event = observer.events[0]
        serialized = repr(event)

        self.assertNotIn("How do I authenticate?", serialized)
        self.assertNotIn("Use an API key.", serialized)
        self.assertNotIn("https://example.com", serialized)

    async def test_logging_observer_serializes_metrics(self) -> None:
        event = RagAnswerObservability(
            query_length=10,
            retrieved_chunk_count=1,
            selected_evidence_count=1,
            citation_count=1,
            insufficient_evidence=False,
            latency_ms=1.5,
            retrieved_chunk_ids=("chunk-auth",),
            citation_chunk_ids=("chunk-auth",),
            access_label_count=1,
            has_owner_identity=False,
        )

        LoggingRagAnswerObserver().record_answer(event)




    async def test_records_below_term_threshold_abstention_diagnostics(
        self,
    ) -> None:
        observer = RecordingObserver()
        repository = FakeAnswerRepository(
            [
                make_chunk(
                    "chunk-auth",
                    "## Authentication\n\nUse an API key.",
                    1.0,
                )
            ]
        )
        service = RagAnswerService(
            RagRetrievalService(repository),
            observer=observer,
        )

        result = await service.answer(
            query="kubernetes ingress tls certificate",
        )

        self.assertTrue(result.insufficient_evidence)
        event = observer.events[0]
        self.assertEqual(event.retrieved_chunk_count, 1)
        self.assertEqual(event.query_term_count, 4)
        self.assertEqual(event.min_matches_required, 2)
        self.assertEqual(event.max_statement_matches, 0)
        self.assertEqual(event.abstention_reason, "below_term_threshold")

    async def test_records_no_chunks_abstention_reason(self) -> None:
        observer = RecordingObserver()
        service = RagAnswerService(
            RagRetrievalService(FakeAnswerRepository([])),
            observer=observer,
        )

        result = await service.answer(query="How do I authenticate?")

        self.assertTrue(result.insufficient_evidence)
        event = observer.events[0]
        self.assertEqual(event.abstention_reason, "no_chunks")
        self.assertEqual(event.max_statement_matches, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
