from typing import Literal

from pydantic import BaseModel, Field


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
        description=(
            "Deployed Git commit SHA, when provided by the hosting platform."
        ),
    )
    environment: str | None = Field(
        default=None,
        description="Deployment environment name, when configured.",
    )


class CacheInfo(BaseModel):
    hit: bool = Field(description="Whether the response was served from cache.")
    layer: str = Field(
        description="Cache layer: 'none', 'memory' or 'persistent'."
    )
    age_seconds: int | None = Field(
        default=None,
        description="Age of the cached entry in seconds, when known.",
    )


class Provenance(BaseModel):
    request_id: str = Field(description="Identifier of the request.")
    fetched_at: str = Field(
        description="UTC ISO 8601 timestamp of the fetch."
    )
    requested_url: str = Field(
        description=(
            "The requested URL with sensitive-looking query parameters removed."
        )
    )
    final_url: str | None = Field(
        default=None,
        description="URL after redirects. Absent for cache hits.",
    )
    canonical_url: str | None = Field(
        default=None,
        description="Canonical URL, if the page declares one.",
    )
    upstream_status: int | None = Field(
        default=None,
        description="Upstream HTTP status. Absent for cache hits.",
    )
    redirect_count: int | None = Field(
        default=None,
        description="Redirects followed. Absent for cache hits.",
    )
    content_type: str | None = Field(
        default=None,
        description="Content type of the fetched response.",
    )
    bytes_fetched: int | None = Field(
        default=None,
        description="Bytes fetched from the upstream source.",
    )
    content_sha256: str | None = Field(
        default=None,
        description="SHA-256 hash of the returned text.",
    )
    cache: CacheInfo | None = Field(
        default=None,
        description="Cache metadata.",
    )
    extractor_version: str | None = Field(
        default=None,
        description="Extractor version.",
    )


class ScrapeTextResponse(BaseModel):
    url: str
    # Length is enforced by extract_text_result() against settings.max_text_characters;
    # duplicating the limit here as a pydantic constraint would turn a raised
    # limit into a response-serialization 500.
    text: str = Field(
        description=(
            "Readable extracted text, limited by the service's configured "
            "character cap."
        )
    )
    truncated: bool = Field(
        description=(
            "True when extracted content exceeded the character cap and text "
            "was shortened."
        )
    )
    cache_layer: Literal["none", "memory", "persistent"] = Field(
        default="none",
        description=(
            "Which cache served the response: 'none' (fresh fetch), "
            "'memory' or 'persistent'."
        ),
    )
    approx_tokens: int = Field(
        default=0,
        description=(
            "Approximate token count of the returned text: "
            "ceil(characters / 4). An estimate, not a tokenizer count."
        ),
    )
    token_method: str = Field(
        default="ceil(characters/4)",
        description="Method used to compute approx_tokens.",
    )
    tokens: int = Field(
        default=0,
        description=(
            "DEPRECATED: same value as approx_tokens, kept for one release "
            "for backward compatibility."
        ),
    )
    tokens_saved_estimate: int = Field(
        default=0,
        description=(
            "Estimated tokens saved by extraction: approximate tokens of the "
            "fetched HTML minus approximate tokens of the returned text, "
            "floored at 0. An estimate."
        ),
    )
    truncated_split: bool = Field(
        default=False,
        description=(
            "Reserved: true when content spans multiple chunks "
            "(not truncation)."
        ),
    )
    provenance: Provenance | None = Field(
        default=None,
        description=(
            "Request provenance. May be absent while this feature is "
            "rolled out."
        ),
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