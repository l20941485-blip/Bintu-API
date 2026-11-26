"""Maps extraction output into the RAG knowledge-core persistence contract."""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Sequence
from dataclasses import dataclass

from bintu_api.extraction.rag_chunking import SemanticChunk
from bintu_api.rag.models import (
    Document,
    DocumentRevision,
    IngestedRevision,
    RagChunk,
)
from bintu_api.rag.repositories import ChunkRepository


@dataclass(frozen=True)
class ExtractionIngestionRequest:
    """Canonical extraction data required to ingest one RAG revision."""

    canonical_url: str
    title: str | None
    source_type: str
    owner_identity: str | None
    source_url: str
    final_url: str | None
    content_sha256: str
    content_fingerprint: str | None
    extracted_at: str
    language: str | None
    status: str
    chunks: Sequence[SemanticChunk]
    access_labels: tuple[str, ...] = ()


class RagIngestionService:
    """Converts semantic extraction chunks into repository-ready RAG chunks."""

    def __init__(self, repository: ChunkRepository) -> None:
        self._repository = repository

    async def ingest(
        self,
        request: ExtractionIngestionRequest,
    ) -> IngestedRevision:
        document = Document(
            document_id=self._document_id(request),
            canonical_url=request.canonical_url,
            title=request.title,
            source_type=request.source_type,
            owner_identity=request.owner_identity,
        )

        revision = DocumentRevision(
            revision_id=None,
            document_id=document.document_id,
            source_url=request.source_url,
            final_url=request.final_url,
            content_sha256=request.content_sha256,
            content_fingerprint=request.content_fingerprint,
            extracted_at=request.extracted_at,
            language=request.language,
            status=request.status,
        )

        chunks = [self._to_rag_chunk(request, chunk) for chunk in request.chunks]
        result = self._repository.ingest_revision(document, revision, chunks)
        if inspect.isawaitable(result):
            result = await result
        return result

    def _document_id(self, request: ExtractionIngestionRequest) -> str:
        material = "\n".join(
            [
                request.canonical_url,
                request.source_type,
            ]
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return f"sha256:{digest}"

    def _to_rag_chunk(
        self,
        request: ExtractionIngestionRequest,
        chunk: SemanticChunk,
    ) -> RagChunk:
        heading_path = tuple(chunk.heading_path)
        section_path = " > ".join(heading_path) if heading_path else None
        return RagChunk(
            chunk_id=chunk.chunk_id,
            revision_id=None,
            document_id=None,
            owner_identity=request.owner_identity,
            chunk_index=chunk.index,
            chunk_strategy=chunk.chunk_strategy,
            text=chunk.text,
            chunk_sha256=hashlib.sha256(chunk.text.encode("utf-8")).hexdigest(),
            heading_path=heading_path,
            section_path=section_path,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            source_url=chunk.source_url or request.source_url,
            final_url=chunk.final_url or request.final_url,
            content_sha256=chunk.content_sha256 or request.content_sha256,
            content_fingerprint=request.content_fingerprint,
            extracted_at=chunk.extracted_at or request.extracted_at,
            access_labels=request.access_labels,
        )
