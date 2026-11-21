"""Canonical domain models for the RAG knowledge core."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Document:
    document_id: str
    canonical_url: str
    title: str | None = None
    source_type: str = "web"
    owner_identity: str | None = None


@dataclass(frozen=True)
class DocumentRevision:
    revision_id: str | None
    document_id: str
    source_url: str
    final_url: str | None
    content_sha256: str
    content_fingerprint: str | None
    extracted_at: str
    language: str | None = None
    status: str = "active"


@dataclass(frozen=True)
class RagChunk:
    chunk_id: str | None
    revision_id: str | None
    document_id: str | None
    owner_identity: str | None
    chunk_index: int
    chunk_strategy: str
    text: str
    chunk_sha256: str | None
    heading_path: tuple[str, ...]
    section_path: str | None
    char_start: int | None
    char_end: int | None
    source_url: str
    final_url: str | None
    content_sha256: str
    content_fingerprint: str | None
    extracted_at: str
    access_labels: tuple[str, ...]


@dataclass(frozen=True)
class IngestedRevision:
    revision_id: str
    document: Document
    revision: DocumentRevision
    chunks: tuple[RagChunk, ...]
