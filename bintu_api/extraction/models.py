"""Transport-neutral models shared by extraction and API response adapters."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class CacheInfo(BaseModel):
    hit: bool = Field(description="Whether the response was served from cache.")
    layer: str = Field(description="Cache layer: 'none', 'memory' or 'persistent'.")
    age_seconds: int | None = Field(
        default=None,
        description="Age of the cached entry in seconds, when known.",
    )
    fresh: bool = Field(
        default=True,
        description=(
            "Whether the result is fresh under Bintu's declared cache policy. "
            "A fresh extraction is always fresh; a cache hit is fresh when its "
            "known age is within the cache TTL."
        ),
    )
    stale_reason: str | None = Field(
        default=None,
        description=(
            "Why a cached entry was considered stale: 'ttl_expired', "
            "'extractor_version_changed', 'missing_timestamp', or "
            "'invalid_timestamp'. None when fresh or when no cache was used."
        ),
    )
    revalidated: bool = Field(
        default=False,
        description=(
            "True when a stale cache entry was refreshed during this request."
        ),
    )


class Provenance(BaseModel):
    request_id: str = Field(description="Identifier of the request.")
    fetched_at: str = Field(description="UTC ISO 8601 timestamp of the fetch.")
    requested_url: str = Field(description="The requested URL with sensitive-looking query parameters removed.")
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
    language: str | None = Field(
        default=None,
        description="Best-known content language, when the source provides it.",
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


class ContentQuality(BaseModel):
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall extraction quality signal from 0.0 to 1.0.",
    )
    boilerplate_ratio: float = Field(
        ge=0.0,
        le=1.0,
        description="Estimated share of extracted text identified as boilerplate.",
    )
    main_content_coverage: float = Field(
        ge=0.0,
        le=1.0,
        description="Estimated share of meaningful pre-cleaning content retained.",
    )
    section_completeness: float = Field(
        ge=0.0,
        le=1.0,
        description="Share of detected sections with a heading and nonempty content.",
    )


class ScrapeTextResponse(BaseModel):
    url: str
    text: str = Field(description="Readable extracted text, limited by the service's configured character cap.")
    truncated: bool = Field(
        description="True when extracted content exceeded the character cap and text was shortened."
    )
    limiting_factor: str | None = Field(
        default=None,
        description="Which limit bound the returned text: character cap or token budget.",
    )
    deduplicated_count: int = Field(
        default=0,
        description="Number of duplicate blocks removed during extraction quality normalization.",
    )
    low_yield: bool = Field(
        default=False,
        description=(
            "True when a large source page produced very little readable text, "
            "often because it requires JavaScript or authentication."
        ),
    )
    yield_hint: str | None = Field(
        default=None,
        description="Optional operator-facing explanation when low_yield is true.",
    )
    selected_sections: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Selected sections returned only when a scrape request supplies "
            "section selectors. Each item includes heading, level, index, and text."
        ),
    )
    requested_sections: list[str] | None = Field(
        default=None,
        description="Section selectors requested by the caller.",
    )
    unmatched_sections: list[str] | None = Field(
        default=None,
        description="Requested section selectors that did not match a heading or label.",
    )
    available_sections: list[str] | None = Field(
        default=None,
        description="Headings and labels available in the extracted document.",
    )
    filtered: bool = Field(
        default=False,
        description="True when a sections filter was applied before mode processing.",
    )
    section_match_status: str = Field(
        default="not_filtered",
        description="Outcome of section selection: not_filtered, matched, partial_match, or no_match.",
    )
    warnings: list[str] | None = Field(
        default=None,
        description="Non-fatal section-selection warnings.",
    )
    cache_layer: Literal["none", "memory", "persistent"] = Field(
        default="none",
        description="Which cache served the response: 'none' (fresh fetch), 'memory' or 'persistent'.",
    )
    cache_hit: bool = Field(
        default=False,
        description="True when the response came from the memory or persistent cache.",
    )
    approx_tokens: int = Field(
        default=0,
        description="Approximate token count of the returned text: ceil(characters / 4).",
    )
    token_method: str = Field(
        default="ceil(characters/4)",
        description="Method used to compute approx_tokens.",
    )
    tokens: int = Field(
        default=0,
        description="DEPRECATED: same value as approx_tokens, kept for backward compatibility.",
    )
    tokens_saved_estimate: int = Field(
        default=0,
        description=(
            "Estimated tokens saved by extraction: approximate tokens of the "
            "fetched HTML minus approximate tokens of the returned text."
        ),
    )
    truncated_split: bool = Field(
        default=False,
        description="Reserved: true when content spans multiple chunks (not truncation).",
    )
    content_cleaning: dict[str, Any] | None = Field(
        default=None,
        description="Reports whether stronger main-content extraction was applied.",
    )
    content_quality: ContentQuality | None = Field(
        default=None,
        description="Quality signals describing extraction usefulness and boilerplate contamination.",
    )
    provenance: Provenance | None = Field(
        default=None,
        description="Request provenance. May be absent while this feature is rolled out.",
    )