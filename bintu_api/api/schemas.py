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
    render_js: bool = False


class VersionResponse(BaseModel):
    service: str
    version: str
    max_html_bytes: int
    max_redirects: int
    max_text_characters: int
    rate_limit_requests: int
    rate_limit_window_seconds: int
    cache_ttl_seconds: int
