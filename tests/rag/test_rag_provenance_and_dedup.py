"""Unit tests for RAG chunk provenance, deduplication, and grounding."""

from __future__ import annotations

import unittest
from typing import Any

from bintu_api.extraction.rag_chunking import SemanticChunk
from bintu_api.rag.answer import RagAnswerService
from bintu_api.rag.ingestion import (
    ExtractionIngestionRequest,
    RagIngestionService,
)
from bintu_api.rag.retrieval import RagRetrievalService, RetrievedChunk


class _FakeIngestionRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any, list[Any]]] = []

    async def ingest_revision(
        self,
        document: Any,
        revision: Any,
        chunks: list[Any],
    ) -> dict[str, Any]:
        self.calls.append((document, revision, chunks))
        return {"document_id": document.document_id, "chunk_count": len(chunks)}


class _ListRetrievalRepository:
    def __init__(self, rows: list[RetrievedChunk]) -> None:
        self._rows = rows

    async def search_chunks(
        self,
        *,
        query: str,
        limit: int,
        access_labels: tuple[str, ...],
        owner_identity: str | None,
        document_id: str | None = None,
    ) -> list[RetrievedChunk]:
        return list(self._rows)


class _StaticAnswerRetriever:
    def __init__(self, chunks: tuple[RetrievedChunk, ...]) -> None:
        self._chunks = chunks

    async def search(
        self,
        *,
        query: str,
        limit: int = 5,
        access_labels: tuple[str, ...] = (),
        owner_identity: str | None = None,
        document_id: str | None = None,
    ) -> list[RetrievedChunk]:
        return list(self._chunks)


def _make_retrieved_chunk(
    *,
    chunk_id: str,
    text: str,
    score: float = 1.0,
    heading_path: tuple[str, ...] = ("Docs",),
    access_labels: tuple[str, ...] = ("public",),
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        revision_id="rev-1",
        document_id="doc-1",
        text=text,
        score=score,
        source_url="https://example.com/docs",
        final_url="https://example.com/docs",
        heading_path=heading_path,
        access_labels=access_labels,
    )


def _make_semantic_chunk(
    *,
    chunk_id: str,
    index: int,
    text: str,
    heading_path: list[str],
    char_start: int,
    char_end: int,
) -> SemanticChunk:
    token_count = max(1, len(text.split()))
    return SemanticChunk(
        index=index,
        text=text,
        approx_tokens=token_count,
        tokens=token_count,
        chunk_strategy="semantic",
        chunk_id=chunk_id,
        heading_path=heading_path,
        char_start=char_start,
        char_end=char_end,
        source_url="https://example.com/auth",
        final_url="https://example.com/auth",
        content_sha256="deadbeef",
        extracted_at="2026-11-26T00:00:00Z",
    )


class RagProvenanceAndDeduplicationTests(unittest.IsolatedAsyncioTestCase):
    async def test_ingestion_preserves_semantic_chunk_provenance(self) -> None:
        repo = _FakeIngestionRepository()
        service = RagIngestionService(repository=repo)
        request = ExtractionIngestionRequest(
            canonical_url="https://example.com/auth",
            title="Authentication Guide",
            source_type="web",
            owner_identity="user-1",
            source_url="https://example.com/auth",
            final_url="https://example.com/auth",
            content_sha256="deadbeef",
            content_fingerprint="fp-1",
            extracted_at="2026-11-26T00:00:00Z",
            language="en",
            status="ready",
            chunks=[
                _make_semantic_chunk(
                    chunk_id="sc-1",
                    index=0,
                    text="Configure your API key first.",
                    heading_path=["Auth", "API Keys"],
                    char_start=12,
                    char_end=40,
                ),
                _make_semantic_chunk(
                    chunk_id="sc-2",
                    index=1,
                    text="Rotate tokens every 30 days.",
                    heading_path=["Auth", "Rotation"],
                    char_start=41,
                    char_end=70,
                ),
            ],
            access_labels=("public",),
        )

        await service.ingest(request)

        self.assertEqual(len(repo.calls), 1)
        _, _, rag_chunks = repo.calls[0]
        self.assertEqual(len(rag_chunks), 2)
        self.assertEqual(rag_chunks[0].heading_path, ("Auth", "API Keys"))
        self.assertEqual(rag_chunks[0].section_path, "Auth > API Keys")
        self.assertEqual(rag_chunks[0].char_start, 12)
        self.assertEqual(rag_chunks[0].char_end, 40)

    async def test_retrieval_deduplicates_by_id_and_normalized_text_honoring_limit(
        self,
    ) -> None:
        repo = _ListRetrievalRepository(
            [
                _make_retrieved_chunk(
                    chunk_id="c-1",
                    text="Use an API key in the Authorization header.",
                    score=0.95,
                ),
                _make_retrieved_chunk(
                    chunk_id="c-1-dup-text",
                    text="  use an api key   in the authorization header.  ",
                    score=0.90,
                ),
                _make_retrieved_chunk(
                    chunk_id="c-2",
                    text="Rate limits allow 100 requests per minute.",
                    score=0.80,
                ),
                _make_retrieved_chunk(
                    chunk_id="c-3",
                    text="Webhooks sign payloads with HMAC.",
                    score=0.70,
                ),
            ]
        )
        retriever = RagRetrievalService(repository=repo)

        results = await retriever.search(query="api key", limit=2)
        self.assertEqual([item.chunk_id for item in results], ["c-1", "c-2"])

    async def test_answer_deduplicates_citations_and_enforces_term_threshold(
        self,
    ) -> None:
        retriever = _StaticAnswerRetriever(
            (
                _make_retrieved_chunk(
                    chunk_id="c-auth",
                    text="Use an API key to authenticate requests.",
                    heading_path=("Guide", "Authentication"),
                ),
                _make_retrieved_chunk(
                    chunk_id="c-auth",
                    text="Another line in the same authentication chunk.",
                    heading_path=("Guide", "Authentication"),
                ),
            )
        )
        answer_service = RagAnswerService(retrieval_service=retriever)

        two_term = await answer_service.answer(query="authentication setup")
        self.assertFalse(two_term.insufficient_evidence)
        self.assertIn("API key", two_term.answer)
        self.assertEqual(
            [citation.chunk_id for citation in two_term.citations],
            ["c-auth"],
        )

        unrelated = await answer_service.answer(
            query="kubernetes ingress controller tls"
        )
        self.assertTrue(unrelated.insufficient_evidence)
        self.assertEqual(unrelated.answer, "")


if __name__ == "__main__":
    unittest.main()
