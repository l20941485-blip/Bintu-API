"""Scrape output, provenance, and cache-URL redaction helpers.

This module owns the shared output boundary used by REST and MCP extraction
surfaces. It does not perform metering or MCP JSON-RPC formatting.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import UTC, datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bintu_api.common.fetch import FetchedHTML, compute_approx_tokens
from bintu_api.extraction.cache import compute_saved_tokens
from bintu_api.extraction.cache_store import CachedMarkdown
from bintu_api.extraction.models import CacheInfo, Provenance, ScrapeTextResponse
from bintu_api.extraction.quality import (
    assess_content_quality,
    assess_yield,
    detect_boilerplate_characters,
)
from bintu_api.security.credentials import CREDENTIAL_QUERY_PARAMS
from bintu_api.security.url_safety import (
    SENSITIVE_QUERY_PARAMETER_NAMES,
    sanitize_url,
)
from bintu_api.settings import Settings

TOKEN_METHOD = "ceil(characters/4)"


def _cache_age_seconds(
    extracted_at: str | None,
    now: datetime,
) -> int | None:
    """Return whole cache age seconds, or None when unknown or invalid."""
    if not extracted_at:
        return None

    try:
        extracted_time = datetime.fromisoformat(
            extracted_at.replace("Z", "+00:00")
        )
    except (ValueError, TypeError):
        return None

    if extracted_time.tzinfo is None:
        return None

    age = (now - extracted_time).total_seconds()
    return 0 if age < 0 else int(age)


def is_sensitive_query_parameter(name: str) -> bool:
    """Return whether a query parameter should be redacted before persistence."""
    normalized = name.strip().lower()
    return normalized in SENSITIVE_QUERY_PARAMETER_NAMES or normalized.startswith("utm_")


def build_provenance(
    url: str,
    text: str,
    document: FetchedHTML | None,
    cache_layer: str,
    request_id: str,
    settings: Settings,
    *,
    extracted_at: str | None = None,
) -> Provenance:
    """Build provenance using real values only; inapplicable fields stay None."""
    fetched = document is not None and cache_layer == "none"
    cache_age_seconds = (
        _cache_age_seconds(extracted_at, datetime.now(UTC))
        if cache_layer != "none"
        else None
    )
    return Provenance(
        request_id=request_id,
        fetched_at=datetime.now(UTC).isoformat(),
        requested_url=sanitize_url(url),
        final_url=document.final_url if fetched else None,
        bytes_fetched=len(document.body) if fetched else None,
        content_sha256=(hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None),
        cache=CacheInfo(
            hit=cache_layer != "none",
            layer=cache_layer,
            age_seconds=cache_age_seconds,
        ),
        extractor_version=getattr(settings, "service_version", "unknown"),
        status=getattr(document, "status", None) if fetched else None,
        redirect_count=getattr(document, "redirect_count", None) if fetched else None,
        content_type=getattr(document, "content_type", None) if fetched else None,
    )


def _count_markdown_sections(text: str) -> tuple[int, int]:
    """Count Markdown headings and those followed by nonempty content."""
    lines = text.splitlines()
    headings = [
        index
        for index, line in enumerate(lines)
        if line.strip().startswith("#")
    ]

    if not headings:
        return 0, 0

    complete = 0
    for position, heading_index in enumerate(headings):
        end = (
            headings[position + 1]
            if position + 1 < len(headings)
            else len(lines)
        )
        if "\n".join(lines[heading_index + 1 : end]).strip():
            complete += 1

    return len(headings), complete


def build_scrape_response(
    url: str,
    result: CachedMarkdown,
    document: FetchedHTML | None,
    cache_layer: str,
    request_id: str,
    settings: Settings,
) -> ScrapeTextResponse:
    """Build the shared scrape response while preserving cache economics."""
    approx_tokens = compute_approx_tokens(result.markdown)

    # Preserve the economics of the original extraction on cache hits. A
    # persistent-cache row no longer has the source HTML, so recomputing savings
    # would incorrectly report zero.
    saved = compute_saved_tokens(document, result, cache_layer)

    assessment = assess_yield(approx_tokens, result.html_tokens)

    pre_cleaning_characters = (
        result.pre_cleaning_characters
        if result.pre_cleaning_characters > 0
        else len(result.markdown)
    )
    section_count, complete_section_count = _count_markdown_sections(
        result.markdown
    )
    quality_assessment = assess_content_quality(
        extracted_characters=len(result.markdown),
        boilerplate_characters=detect_boilerplate_characters(result.markdown),
        pre_cleaning_characters=pre_cleaning_characters,
        total_sections=section_count,
        complete_sections=complete_section_count,
    )

    return ScrapeTextResponse(
        url=url,
        text=result.markdown,
        truncated=result.truncated,
        cache_hit=cache_layer != "none",
        cache_layer=cache_layer,
        approx_tokens=approx_tokens,
        token_method=TOKEN_METHOD,
        tokens=approx_tokens,
        tokens_saved_estimate=saved,
        low_yield=assessment.low_yield,
        yield_hint=assessment.hint,
        content_cleaning=result.content_cleaning
        or {"applied": False, "strategy": "standard"},
        content_quality=asdict(quality_assessment),
        provenance=build_provenance(
            url,
            result.markdown,
            document,
            cache_layer,
            request_id,
            settings,
            extracted_at=result.extracted_at,
        ),
    )


def redact_cache_url(url: str) -> str:
    """Redact credential-like query values before persistent-cache storage.


    Cache lookups continue to use the original request URL. Only the URL
    written to Supabase is redacted, preventing bearer tokens, session IDs,
    and similar caller credentials from being retained in cache rows.
    """
    parsed = urlsplit(url)
    if not parsed.query:
        return url

    try:
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
    except ValueError:
        return url

    redacted_pairs = [
        (name, "[REDACTED]" if name.lower() in CREDENTIAL_QUERY_PARAMS else value) for name, value in pairs
    ]

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(redacted_pairs),
            parsed.fragment,
        )
    )
