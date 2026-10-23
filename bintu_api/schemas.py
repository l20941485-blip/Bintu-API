from typing import Literal

from pydantic import BaseModel, Field

import math


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


class ScrapeTextResponse(BaseModel):
    url: str
    # Length is enforced by extract_text_result() against settings.max_text_characters;
    # duplicating the limit here as a pydantic constraint would turn a raised
    # limit into a response-serialization 500.
    text: str = Field(
        description="Readable extracted text, limited by the service's configured character cap."
    )
    truncated: bool = Field(
        description="True when extracted content exceeded the character cap and text was shortened."
    )
    cache_layer: Literal["none", "memory", "persistent"] = Field(
        default="none",
        description="Indicates which cache layer served the response: 'none' (fresh fetch), 'memory' (in-memory cache), or 'persistent' (Supabase cache).",
    )
    approx_tokens: int = Field(
        description="Approximate token count of the delivered text, computed as ceil(characters / 4) using a whitespace-split tokenizer (no tiktoken dependency).",
    )
    token_method: str = Field(
        default="ceil(characters/4)",
        description="Tokenization method used for approx_tokens computation.",
    )
    tokens: int = Field(
        alias="approx_tokens",
        description="DEPRECATED: Alias for approx_tokens. Preserved for backward compatibility. Represents a character bound, not a physical hardware tokenizer configuration.",
    )
    tokens_saved_estimate: int = Field(
        description="Estimated structural payload reduction: approx_tokens(fetched HTML content) - approx_tokens(extracted Markdown output text), floored at 0.",
    )
    effective_char_cap: int = Field(
        description="Effective character cap: min(tier_threshold, max_tokens * 4). Boundary precedence: char cap binds before token budget.",
    )
    truncated_split: bool = Field(
        description="True when content spans across multiple processing blocks (split), distinguished from truncated which means actual content loss.",
    )
    provenance: "Provenance" = Field(
        description="Audit-logged provenance metadata tracking all core REST and MCP response data.",
    )


class Provenance(BaseModel):
    request_id: str = Field(
        description="UUID4 string identifying the request."
    )
    fetched_at: str = Field(
        description="UTC ISO 8601 timestamp of when the fetch was initiated."
    )
    requested_url: str = Field(
        description="Sanitized URL with all sensitive query strings fully stripped."
    )
    final_url: str = Field(
        description="Fully resolved target destination URL after following redirects."
    )
    canonical_url: str | None = Field(
        default=None,
        description="Canonical URL, or string_null if not applicable."
    )
    upstream_status: int = Field(
        description="Upstream HTTP status code (e.g. 200)."
    )
    redirect_count: int = Field(
        description="Number of redirects followed during fetch."
    )
    content_type: str = Field(
        description="MIME content type of the fetched response (e.g. text/html)."
    )
    bytes_fetched: int = Field(
        description="Number of bytes fetched from the upstream source."
    )
    content_sha256: str = Field(
        description="SHA256 hash of the returned text content."
    )
    cache: "CacheInfo" = Field(
        description="Cache hit metadata."
    )
    extractor_version: str = Field(
        description="Extractor version that produced this response."
    )
    removed: "RemovedStats" = Field(
        description="Statistical cleaning metrics (instructional, NOT a security control validation layer)."
    )


class CacheInfo(BaseModel):
    hit: bool = Field(
        description="Whether the response was served from cache."
    )
    layer: str = Field(
        description="Cache layer: 'memory' or 'persistent'."
    )
    age_seconds: int = Field(
        description="Age of cached entry in seconds."
    )


class RemovedStats(BaseModel):
    hidden_elements: int = Field(
        description="Number of hidden elements removed during extraction."
    )
    zero_width_chars: int = Field(
        description="Number of zero-width characters removed during extraction."
    )
    comments: int = Field(
        description="Number of HTML comments removed during extraction."
    )


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
