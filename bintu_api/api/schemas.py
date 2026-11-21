"""Shared data schemas for Bintu responses and requests.

This module defines the public contract used by API and MCP surfaces while avoiding direct business logic.

Important boundaries, invariants, and compatibility notes are documented here so the module stays focused on its owned behavior without drifting into unrelated routing or storage concerns.
"""

from typing import Literal

from pydantic import BaseModel, Field

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
