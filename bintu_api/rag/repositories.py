"""Repository contracts and an in-memory implementation for RAG ingestion."""

from __future__ import annotations

import hashlib
import uuid
from typing import Protocol

from bintu_api.extraction.rag_chunking import make_chunk_id
from bintu_api.rag.models import (
    Document,
    DocumentRevision,
    IngestedRevision,
    RagChunk,
)


class ChunkRepository(Protocol):
    """Persist and retrieve canonical RAG chunks."""

    def ingest_revision(
        self,
        document: Document,
        revision: DocumentRevision,
        chunks: list[RagChunk],
    ) -> IngestedRevision:
        """Ingest one document revision and its chunks."""
        ...


class InMemoryChunkRepository:
    """In-memory repository used for domain contract tests."""

    def __init__(self) -> None:
        self._documents: dict[str, Document] = {}
        self._revisions: dict[tuple[str, str], IngestedRevision] = {}

    def ingest_revision(
        self,
        document: Document,
        revision: DocumentRevision,
        chunks: list[RagChunk],
    ) -> IngestedRevision:
        revision_key = (document.document_id, revision.content_sha256)

        existing = self._revisions.get(revision_key)
        if existing is not None:
            return existing

        revision_id = uuid.uuid4().hex
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
            )
            for chunk in chunks
        )

        result = IngestedRevision(
            revision_id=revision_id,
            document=document,
            revision=persisted_revision,
            chunks=persisted_chunks,
        )
        self._documents[document.document_id] = document
        self._revisions[revision_key] = result
        return result

    def _persist_chunk(
        self,
        *,
        document: Document,
        revision: DocumentRevision,
        chunk: RagChunk,
    ) -> RagChunk:
        chunk_sha256 = hashlib.sha256(chunk.text.encode("utf-8")).hexdigest()
        chunk_id = make_chunk_id(
            source_url=revision.source_url,
            content_sha256=revision.content_sha256,
            chunk_strategy=chunk.chunk_strategy,
            chunk_index=chunk.chunk_index,
        )

        return RagChunk(
            chunk_id=chunk_id,
            revision_id=revision.revision_id,
            document_id=document.document_id,
            tenant_id=document.tenant_id,
            chunk_index=chunk.chunk_index,
            chunk_strategy=chunk.chunk_strategy,
            text=chunk.text,
            chunk_sha256=chunk_sha256,
            heading_path=chunk.heading_path,
            section_path=chunk.section_path,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            source_url=revision.source_url,
            final_url=revision.final_url,
            content_sha256=revision.content_sha256,
            content_fingerprint=revision.content_fingerprint,
            extracted_at=revision.extracted_at,
            access_labels=chunk.access_labels,
        )
