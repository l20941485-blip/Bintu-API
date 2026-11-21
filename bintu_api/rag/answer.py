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

        evidence: list[tuple[RetrievedChunk, str]] = []
        seen_statements: set[str] = set()

        for chunk in chunks:
            statement = self._extract_answer(chunk.text)
            if not statement:
                continue

            normalized = statement.casefold()
            if normalized in seen_statements:
                continue

            seen_statements.add(normalized)
            evidence.append((chunk, statement))

            if len(evidence) == 3:
                break

        if not evidence:
            return RagAnswer(
                answer="",
                citations=(),
                retrieved_chunks=tuple(chunks),
                insufficient_evidence=True,
            )

        return RagAnswer(
            answer=" ".join(statement for _, statement in evidence),
            citations=tuple(
                self._to_citation(chunk)
                for chunk, _ in evidence
            ),
            retrieved_chunks=tuple(chunks),
            insufficient_evidence=False,
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
