"""Grounded, extractive answer generation for the RAG knowledge core."""

from __future__ import annotations

from dataclasses import dataclass

from bintu_api.rag.retrieval import RagRetrievalService, RetrievedChunk


@dataclass(frozen=True)
class RagCitation:
    """A chunk-level citation attached to a grounded answer."""

    chunk_id: str
    revision_id: str
    document_id: str
    source_url: str
    final_url: str | None
    heading_path: tuple[str, ...]


@dataclass(frozen=True)
class RagAnswer:
    """A grounded answer and the evidence used to produce it."""

    answer: str
    citations: tuple[RagCitation, ...]
    retrieved_chunks: tuple[RetrievedChunk, ...]
    insufficient_evidence: bool


class RagAnswerService:
    """Produces extractive answers strictly from retrieved evidence."""

    def __init__(self, retrieval_service: RagRetrievalService) -> None:
        self._retrieval_service = retrieval_service

    async def answer(
        self,
        *,
        query: str,
        limit: int = 5,
        access_labels: tuple[str, ...] = (),
        owner_identity: str | None = None,
    ) -> RagAnswer:
        chunks = await self._retrieval_service.search(
            query=query,
            limit=limit,
            access_labels=access_labels,
            owner_identity=owner_identity,
        )

        if not chunks:
            return RagAnswer(
                answer="",
                citations=(),
                retrieved_chunks=(),
                insufficient_evidence=True,
            )

        best = chunks[0]
        answer = self._extract_answer(best.text)

        return RagAnswer(
            answer=answer,
            citations=(self._to_citation(best),),
            retrieved_chunks=tuple(chunks),
            insufficient_evidence=not answer,
        )

    def _extract_answer(self, text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            return stripped

        return ""

    def _to_citation(self, chunk: RetrievedChunk) -> RagCitation:
        return RagCitation(
            chunk_id=chunk.chunk_id,
            revision_id=chunk.revision_id,
            document_id=chunk.document_id,
            source_url=chunk.source_url,
            final_url=chunk.final_url,
            heading_path=chunk.heading_path,
        )
