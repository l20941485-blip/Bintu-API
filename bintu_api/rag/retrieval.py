"""Keyword retrieval over the RAG knowledge core."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RetrievedChunk:
    """A retrieval result with enough provenance to support citations."""

    chunk_id: str
    revision_id: str
    document_id: str
    text: str
    score: float
    source_url: str
    final_url: str | None
    heading_path: tuple[str, ...]
    access_labels: tuple[str, ...]


class RetrievalRepository(Protocol):
    """Retrieves authorization-filtered RAG chunks."""

    async def search_chunks(
        self,
        *,
        query: str,
        limit: int,
        access_labels: tuple[str, ...],
        owner_identity: str | None,
        document_id: str | None = None,
    ) -> list[RetrievedChunk]:
        ...


class RagRetrievalService:
    """Provides a keyword retrieval baseline for RAG queries."""

    def __init__(self, repository: RetrievalRepository) -> None:
        self._repository = repository

    async def search(
        self,
        *,
        query: str,
        limit: int = 8,
        access_labels: tuple[str, ...] = (),
        owner_identity: str | None = None,
        document_id: str | None = None,
    ) -> list[RetrievedChunk]:
        if not query or not query.strip():
            raise ValueError("query must not be blank")

        if limit <= 0:
            raise ValueError("limit must be positive")

        rows = await self._repository.search_chunks(
            query=query.strip(),
            limit=limit,
            access_labels=access_labels,
            owner_identity=owner_identity,
            document_id=document_id,
        )
        return self._deduplicate_chunks(rows, limit=limit)

    def _deduplicate_chunks(
        self,
        chunks: list[RetrievedChunk],
        *,
        limit: int,
    ) -> list[RetrievedChunk]:
        deduped: list[RetrievedChunk] = []
        seen_ids: set[str] = set()
        seen_texts: set[str] = set()

        for chunk in chunks:
            normalized_text = " ".join(chunk.text.split()).casefold()
            if chunk.chunk_id in seen_ids or normalized_text in seen_texts:
                continue
            seen_ids.add(chunk.chunk_id)
            seen_texts.add(normalized_text)
            deduped.append(chunk)
            if len(deduped) >= limit:
                break

        return deduped
