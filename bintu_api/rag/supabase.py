"""Supabase-backed persistence adapter for the RAG knowledge core."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from bintu_api.extraction.rag_chunking import make_chunk_id
from bintu_api.rag.models import (
    Document,
    DocumentRevision,
    IngestedRevision,
    RagChunk,
)


class SupabaseChunkRepository:
    """Persist RAG revisions and chunks through a transactional Supabase RPC."""

    def __init__(self, supabase_client: Any) -> None:
        self._supabase_client = supabase_client

    async def ingest_revision(
        self,
        document: Document,
        revision: DocumentRevision,
        chunks: list[RagChunk],
    ) -> IngestedRevision:
        response = await self._supabase_client.rpc(
            "ingest_rag_revision",
            {
                "p_document": {
                    "canonical_url": document.canonical_url,
                    "title": document.title,
                    "source_type": document.source_type,
                    "owner_identity": document.owner_identity,
                },
                "p_revision": {
                    "source_url": revision.source_url,
                    "final_url": revision.final_url,
                    "content_sha256": revision.content_sha256,
                    "content_fingerprint": revision.content_fingerprint,
                    "extracted_at": revision.extracted_at,
                    "language": revision.language,
                    "status": revision.status,
                },
                "p_chunks": [self._chunk_payload(chunk) for chunk in chunks],
            },
        ).execute()

        data = response.data
        revision_id = data["revision_id"]
        chunk_results = data.get("chunks", [])

        persisted_revision = DocumentRevision(
            revision_id=revision_id,
            document_id=document.document_id,
            source_url=revision.source_url,
            final_url=revision.final_url,
            content_sha256=revision.content_sha256,
            content_fingerprint=revision.content_fingerprint,
            extracted_at=revision.extracted_at,
            language=revision.language,
            status=revision.status,
        )

        persisted_chunks = tuple(
            self._persist_chunk(
                document=document,
                revision=persisted_revision,
                chunk=chunk,
                result=chunk_results[index],
            )
            for index, chunk in enumerate(chunks)
        )

        return IngestedRevision(
            revision_id=revision_id,
            document=document,
            revision=persisted_revision,
            chunks=persisted_chunks,
        )

    def _chunk_payload(self, chunk: RagChunk) -> dict[str, Any]:
        chunk_sha256 = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        chunk_id = make_chunk_id(
            source_url=chunk.source_url,
            content_sha256=chunk.content_sha256,
            chunk_strategy=chunk.chunk_strategy,
            chunk_index=chunk.chunk_index,
        )

        return {
            "chunk_id": chunk_id,
            "chunk_index": chunk.chunk_index,
            "chunk_strategy": chunk.chunk_strategy,
            "text": chunk.text,
            "chunk_sha256": chunk_sha256,
            "heading_path": list(chunk.heading_path),
            "section_path": chunk.section_path,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
            "source_url": chunk.source_url,
            "final_url": chunk.final_url,
            "content_sha256": chunk.content_sha256,
            "content_fingerprint": chunk.content_fingerprint,
            "extracted_at": chunk.extracted_at,
            "access_labels": list(chunk.access_labels),
        }

    def _persist_chunk(
        self,
        *,
        document: Document,
        revision: DocumentRevision,
        chunk: RagChunk,
        result: dict[str, Any],
    ) -> RagChunk:
        return RagChunk(
            chunk_id=result["chunk_id"],
            revision_id=revision.revision_id,
            document_id=document.document_id,
            owner_identity=document.owner_identity,
            chunk_index=chunk.chunk_index,
            chunk_strategy=chunk.chunk_strategy,
            text=chunk.text,
            chunk_sha256=result["chunk_sha256"],
            heading_path=chunk.heading_path,
            section_path=chunk.section_path,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            source_url=chunk.source_url,
            final_url=chunk.final_url,
            content_sha256=chunk.content_sha256,
            content_fingerprint=chunk.content_fingerprint,
            extracted_at=chunk.extracted_at,
            access_labels=chunk.access_labels,
        )


@dataclass(frozen=True)
class DocumentSummary:
    """A user-owned document summary for knowledge management."""

    document_id: str
    canonical_url: str
    title: str | None
    source_type: str
    created_at: str
    updated_at: str
    revision_count: int


class SupabaseDocumentRepository:
    """Lists user-owned RAG documents through a Supabase RPC."""

    def __init__(self, supabase_client: Any) -> None:
        self._supabase_client = supabase_client

    async def list_documents(
        self,
        *,
        owner_identity: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[DocumentSummary], int]:
        response = await self._supabase_client.rpc(
            "list_rag_documents",
            {
                "p_owner_identity": owner_identity,
                "p_limit": limit,
                "p_offset": offset,
            },
        ).execute()

        rows = response.data or []

        documents = [
            DocumentSummary(
                document_id=row["document_id"],
                canonical_url=row["canonical_url"],
                title=row.get("title"),
                source_type=row["source_type"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                revision_count=int(row["revision_count"]),
            )
            for row in rows
        ]

        total = int(rows[0]["total"]) if rows else 0

        return documents, total


class SupabaseDocumentDeletionRepository:
    """Deletes user-owned RAG documents through a Supabase RPC."""

    def __init__(self, supabase_client: Any) -> None:
        self._supabase_client = supabase_client

    async def delete_document(
        self,
        *,
        owner_identity: str,
        document_id: str,
    ) -> bool:
        response = await self._supabase_client.rpc(
            "delete_rag_document",
            {
                "p_owner_identity": owner_identity,
                "p_document_id": document_id,
            },
        ).execute()

        return bool(response.data)
