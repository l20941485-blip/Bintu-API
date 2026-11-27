"""Supabase-backed keyword retrieval for the RAG knowledge core."""

from __future__ import annotations

from typing import Any

from bintu_api.integrations.supabase import execute_supabase_rpc
from bintu_api.rag.retrieval import RetrievedChunk


class SupabaseRetrievalRepository:
    """Retrieves RAG chunks through a Supabase RPC."""

    def __init__(self, supabase_client: Any) -> None:
        self._supabase_client = supabase_client

    async def search_chunks(
        self,
        *,
        query: str,
        limit: int,
        access_labels: tuple[str, ...],
        owner_identity: str | None,
        document_id: str | None = None,
    ) -> list[RetrievedChunk]:
        response = await execute_supabase_rpc(
            self._supabase_client,
            "search_rag_chunks",
            {
                "p_query": query,
                "p_limit": limit,
                "p_access_labels": list(access_labels),
                "p_owner_identity": owner_identity,
                "p_document_id": document_id,
            },
        )

        return [self._to_retrieved_chunk(row) for row in response.data or []]

    def _to_retrieved_chunk(self, row: dict[str, Any]) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=row["chunk_id"],
            revision_id=row["revision_id"],
            document_id=row["document_id"],
            text=row["text"],
            score=float(row["score"]),
            source_url=row["source_url"],
            final_url=row.get("final_url"),
            heading_path=tuple(row.get("heading_path") or ()),
            access_labels=tuple(row.get("access_labels") or ()),
        )
