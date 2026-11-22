"""Shared data schemas for Bintu responses and requests.

This module defines the public contract used by API and MCP surfaces while avoiding direct business logic.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from bintu_api.extraction.models import CacheInfo as CacheInfo
from bintu_api.extraction.models import Provenance as Provenance
from bintu_api.extraction.models import ScrapeTextResponse as ScrapeTextResponse


class ErrorDetail(BaseModel):
    code: str
    message: str
    hint: str | None = None


class ErrorResponse(BaseModel):
    detail: ErrorDetail


class GatewayResponse(BaseModel):
    status: str
    service: str
    docs: str


class HealthResponse(BaseModel):
    status: str
    version: str = Field(description="Deployed service version.")
    commit: str | None = Field(
        default=None,
        description=("Deployed Git commit SHA, when provided by the hosting platform."),
    )
    environment: str | None = Field(
        default=None,
        description="Deployment environment name, when configured.",
    )


class RestChunk(BaseModel):
    index: int
    text: str
    approx_tokens: int
    tokens: int
    chunk_strategy: Literal["sequential", "semantic"] = "sequential"
    chunk_id: str | None = None
    heading_path: list[str] | None = None
    char_start: int | None = None
    char_end: int | None = None
    reassembled: bool | None = None
    section_index: int | None = None
    contains_code: bool | None = None
    contains_table: bool | None = None
    contains_links: bool | None = None
    link_count: int | None = None
    source_url: str | None = None
    final_url: str | None = None
    content_sha256: str | None = None
    extracted_at: str | None = None
    page_title: str | None = None
    content_fingerprint: str | None = None
    chunk_sha256: str | None = None
    page_context: str | None = None


class ScrapeChunksResponse(BaseModel):
    url: str
    mode: Literal["chunk"]
    max_tokens: int
    tokens: int
    approx_tokens: int
    html_tokens: int
    token_method: str
    limiting_factor: str
    chunk_count: int
    cache_hit: bool
    cache_layer: Literal["none", "memory", "persistent"]
    revalidated: bool = False
    source_url: str
    extracted_at: str
    tokens_saved_estimate: int
    truncated: bool
    split: bool
    chunks: list[RestChunk]


class MobileScrapeTextRequest(BaseModel):
    url: str
    include_nav: bool = False
    include_header: bool = False
    include_footer: bool = False
    main_content_only: bool = False
    exclude_terminal_sections: bool = False
    summary_mode: Literal["none", "leading", "key_sentences"] = "none"
    summary_sentence_count: int = Field(default=3, ge=1, le=10)
    render_js: bool = False
    chunk_strategy: Literal["sequential", "semantic"] = "sequential"
    overlap_tokens: int = Field(default=0, ge=0, le=1000)



class VersionResponse(BaseModel):
    service: str
    version: str
    max_html_bytes: int
    max_redirects: int
    max_text_characters: int
    rate_limit_requests: int
    rate_limit_window_seconds: int
    cache_ttl_seconds: int


class RagAnswerCitation(BaseModel):
    chunk_id: str
    revision_id: str
    document_id: str
    source_url: str
    final_url: str | None = None
    heading_path: list[str] = Field(default_factory=list)


class RagAnswerRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)
    access_labels: list[str] = Field(default_factory=list)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        query = value.strip()
        if not query:
            raise ValueError("query must not be blank")
        return query


class RagAnswerResponse(BaseModel):
    answer: str
    insufficient_evidence: bool
    citations: list[RagAnswerCitation]


class MobileRagAnswerRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)
    access_labels: list[str] = Field(default_factory=list)
    document_id: str | None = Field(default=None, min_length=1, max_length=100)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        query = value.strip()
        if not query:
            raise ValueError("query must not be blank")
        return query


class MobileRagIngestRequest(BaseModel):
    url: str
    max_tokens: int = Field(default=1000, ge=100, le=50000)
    overlap_tokens: int = Field(default=0, ge=0, le=1000)
    access_labels: list[str] = Field(default_factory=list)


class MobileRagIngestedChunk(BaseModel):
    chunk_id: str
    chunk_index: int
    chunk_sha256: str


class MobileRagIngestResponse(BaseModel):
    document_id: str
    revision_id: str
    chunk_count: int
    chunks: list[MobileRagIngestedChunk]


class RagDocsAnswerRequest(BaseModel):
    """Request for answers restricted to Bintu documentation."""

    query: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=5, ge=1, le=20)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        query = value.strip()
        if not query:
            raise ValueError("query must not be blank")
        return query


class RagDocsIngestRequest(BaseModel):
    """Request to ingest a public documentation page into the docs collection."""

    url: str
    max_tokens: int = Field(default=1000, ge=100, le=50000)
    overlap_tokens: int = Field(default=0, ge=0, le=1000)


class MobileRagDocument(BaseModel):
    """A document owned by the authenticated mobile user."""

    document_id: str
    canonical_url: str
    title: str | None = None
    source_type: str
    created_at: str
    updated_at: str
    revision_count: int


class MobileRagDocumentsResponse(BaseModel):
    """A paginated list of documents owned by the authenticated user."""

    documents: list[MobileRagDocument]
    total: int
    limit: int
    offset: int


class MobileRagDocumentDeleteResponse(BaseModel):
    """Result of deleting a user-owned knowledge document."""

    document_id: str
    deleted: bool


class MobileRagDocumentMetadata(BaseModel):
    """Metadata for a user-owned knowledge document."""

    document_id: str
    canonical_url: str
    title: str | None = None
    source_type: str
    created_at: str
    updated_at: str


class MobileRagRevisionMetadata(BaseModel):
    """Metadata for the latest revision of a knowledge document."""

    revision_id: str
    source_url: str
    final_url: str | None = None
    extracted_at: str
    status: str


class MobileRagChunkPreview(BaseModel):
    """A bounded preview of a retrievable knowledge chunk."""

    chunk_id: str
    chunk_index: int
    heading_path: list[str] = Field(default_factory=list)
    preview: str


class MobileRagDocumentDetailResponse(BaseModel):
    """Detailed metadata and chunk previews for a user-owned document."""

    document: MobileRagDocumentMetadata
    revision: MobileRagRevisionMetadata
    chunk_count: int
    chunks: list[MobileRagChunkPreview]


class MobileRagDocumentRefreshRequest(BaseModel):
    """Request to refresh a user-owned knowledge document."""

    max_tokens: int = Field(default=1000, ge=100, le=50000)
    overlap_tokens: int = Field(default=0, ge=0, le=1000)
    access_labels: list[str] = Field(default_factory=list)
