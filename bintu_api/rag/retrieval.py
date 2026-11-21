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
    ) -> list[RetrievedChunk]:
        if not query or not query.strip():
            raise ValueError("query must not be blank")

        if limit <= 0:
            raise ValueError("limit must be positive")

        return await self._repository.search_chunks(
            query=query.strip(),
            limit=limit,
            access_labels=access_labels,
            owner_identity=owner_identity,
        )
