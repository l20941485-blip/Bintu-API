"""Context pipeline: token-counted, cache-aware extraction modes for RAG-ready documents.


Modes:
    scrape    — plain readable text (existing behavior), with token count + provenance
    chunk     — text split into max_tokens-sized chunks, each with token count,
                ready to drop straight into a vector database
    summarize — condensed text truncated to max_tokens (sentence-aware)


Designed for AI-agent context engineering: instead of returning a raw blob of
Markdown, the server reports token counts, chunk boundaries, and cache hits so
agents and callers can budget LLM context precisely.
"""


from __future__ import annotations


import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal


from fastapi import Request


from bintu_api.auth import rate_limit_identity
from bintu_api.context_chunking import split_into_chunks, summarize_text
from bintu_api.cache import TTLCache
from bintu_api.observability import (
    log_cache_lookup_completed,
    record_cache_tokens_saved,
)
from bintu_api.scraper import FetchedHTML, extract_text_result
from bintu_api.settings import Settings
from bintu_api.schemas import CacheInfo


logger = logging.getLogger("bintu_api.context")


ContextMode = Literal["scrape", "chunk", "summarize"]

DEFAULT_MAX_TEXT_CHARACTERS = 6_000
MAX_EXTRACTION_CHARACTERS = 200_000


def resolve_effective_char_cap(
    requested_max_tokens: int,
    configured_char_cap: int,
    default_char_cap: int = DEFAULT_MAX_TEXT_CHARACTERS,
) -> int:
    """Resolve the extraction character cap for a request.

    The default character cap is a floor: a larger max_tokens budget may
    raise it. An operator-configured non-default cap is a hard ceiling and
    is never overridden by a caller's token budget.
    """
    if configured_char_cap != default_char_cap:
        return min(configured_char_cap, MAX_EXTRACTION_CHARACTERS)

    if requested_max_tokens <= 0:
        return min(configured_char_cap, MAX_EXTRACTION_CHARACTERS)

    token_derived_cap = requested_max_tokens * 4
    effective_cap = max(configured_char_cap, token_derived_cap)
    return min(effective_cap, MAX_EXTRACTION_CHARACTERS)

# Pitch-name aliases: marketing copy uses "chunked" / "chunk_token_budget"
# while the canonical protocol stays "chunk" / "max_tokens" so existing
# Claude connectors never break. Normalization is case/whitespace tolerant.
from bintu_api.extraction_quality import (
    dedupe_blocks,
    normalize_markdown,
    strip_noise_lines,
    truncate_to_token_budget,
)

MODE_ALIASES = {"chunked": "chunk"}



def normalize_mode(value: Any) -> str:
    """Normalize a mode value to its canonical form (case/whitespace tolerant).


    Raises ValueError for unknown modes so callers can reject them with
    HTTP 400 (REST) or JSON-RPC -32602 (MCP) instead of a 500.
    """
    if not isinstance(value, str):
        return value  # type: ignore[return-value]
    cleaned = value.strip().lower()
    canonical = MODE_ALIASES.get(cleaned, cleaned)
    if canonical not in ("scrape", "chunk", "summarize"):
        raise ValueError(f"Unknown context mode: {value!r}")
    return canonical



# Approximate token method: ceil(characters/4) - dependency-free token counting
TOKEN_METHOD = "ceil(characters/4)"



def count_tokens(text: str) -> int:
    """Return an approximate token count for ``text`` (dependency-free)."""
    from bintu_api.scraper import _compute_approx_tokens


    return _compute_approx_tokens(text)



@dataclass(frozen=True)
class ContextResult:
    mode: ContextMode
    text: str
    approx_tokens: int
    html_tokens: int
    token_method: str
    limiting_factor: str
    # Deprecated alias for approx_tokens, kept for one release so existing
    # clients reading `tokens` do not break (Phase 1b, item 3).
    tokens: int = 0
    chunk_count: int = 0
    cache_hit: bool = False
    cache_layer: Literal["none", "memory", "persistent"] = "none"
    chunks: list[dict[str, Any]] | None = None
    source_url: str = ""
    extracted_at: str = ""
    tokens_saved_estimate: int = 0
    truncated: bool = False
    deduplicated_count: int = 0
    split: bool = False
    # Provenance (added in Phase D): additive for both REST and MCP surfaces.
    request_id: str | None = None
    fetched_at: str | None = None
    requested_url: str | None = None
    final_url: str | None = None
    content_type: str | None = None
    bytes_fetched: int | None = None
    content_sha256: str | None = None
    cache: CacheInfo | None = None
    extractor_version: str | None = None



@dataclass(frozen=True)
class CacheEconomics:
    """Extraction economics preserved across persistent-cache hits."""


    html_tokens: int
    tokens_saved_estimate: int
    limiting_factor: str
    truncated: bool
    extracted_at: str



def _decode_source_text(document: FetchedHTML) -> str:
    """Decode a fetched body for the savings baseline (best effort, no throws).


    The baseline deliberately counts the raw document — markup included — so
    `tokens_saved_estimate` is approximately "fetched HTML tokens minus
    delivered text tokens", the all-in number the cost-reduction story needs.
    """
    try:
        if document.charset:
            return document.body.decode(document.charset, errors="replace")
        return document.body.decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover - decoder lookup is already guarded
        return ""



def _sentences(text: str) -> list[str]:
    """Split prose into sentences while preserving terminal punctuation."""
    sentence_pattern = re.compile(
        r"""
        (?P<sentence>
            [^.!?]+            # sentence body
            [.!?]+             # terminal punctuation
            ["')\]]*           # optional closing quotes/brackets
        )
        (?P<space>\s+|$)
        """,
        re.VERBOSE,
    )


    sentences: list[str] = []
    position = 0


    for match in sentence_pattern.finditer(text):
        if match.start() > position:
            remainder = text[position : match.start()].strip()
            if remainder:
                sentences.append(remainder)
        sentences.append(match.group("sentence").strip())
        position = match.end()


    if position < len(text):
        remainder = text[position:].strip()
        if remainder:
            sentences.append(remainder)


    return [sentence for sentence in sentences if sentence]



def _is_table_block(block: str) -> bool:
    """Recognize pipe-delimited tables, with or without outer pipes."""
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    return len(lines) >= 2 and all("|" in line for line in lines)



async def extract_context(
    request: Request,
    url: str,
    mode: ContextMode = "scrape",
    max_tokens: int = 6000,
    cache: bool = True,
    render_js: bool = False,
    include_nav: bool = False,
    include_header: bool = False,
    include_footer: bool = False,
    identity: str | None = None,
    raw_text: str | None = None,
    content_truncated: bool = False,
    html_source_text: str | None = None,
    cache_hit: bool = False,
    cache_layer: str = "none",
    document: FetchedHTML | None = None,
    settings: Settings | None = None,
    cache_economics: CacheEconomics | None = None,
    extracted_at: str | None = None,
) -> ContextResult:
    """Fetch, extract, and transform a page into a context-ready document.


    Reuses the existing fetch → extract → cache pipeline from
    ``bintu_api.routes._scrape_text`` (rate limiting, SSRF guards, 1 MiB cap,
    Supabase + memory cache all intact), then applies the requested mode.
    """
    if settings is None:
        settings = request.app.state.settings
    if identity is None:
        identity = rate_limit_identity(request, settings)


    # Canonicalize pitch-name aliases up front so downstream logic always
    # operates on canonical values. The caller supplies the extraction inputs;
    # this function must not overwrite them.
    mode = normalize_mode(mode)  # type: ignore[assignment]
    if mode not in ("scrape", "chunk", "summarize"):
        raise ValueError(f"Unknown context mode: {mode}")


    raw_text = raw_text or ""
    html_source_text = html_source_text or ""


    # Preserve the original extraction economics when serving from a
    # persistent cache. Without this, a cache hit would incorrectly report
    # html_tokens=0 and tokens_saved_estimate=0 because the original HTML
    # is no longer available.
    if cache_hit and cache_economics is not None:
        html_tokens = cache_economics.html_tokens
        tokens_saved_estimate: int | None = (
            cache_economics.tokens_saved_estimate
        )
        resolved_extracted_at = cache_economics.extracted_at
    else:
        html_tokens = count_tokens(html_source_text)
        tokens_saved_estimate = None
        resolved_extracted_at = (
            extracted_at or datetime.now(timezone.utc).isoformat()
        )


    # Cache lookup observability (Phase 4): measure hit/miss distribution and
    # persistent-cache freshness without logging the raw target URL.
    cache_age_seconds: float | None = None
    if cache_hit and resolved_extracted_at:
        try:
            extracted_time = datetime.fromisoformat(
                resolved_extracted_at.replace("Z", "+00:00")
            )
            cache_age_seconds = max(
                0.0,
                (
                    datetime.now(timezone.utc) - extracted_time
                ).total_seconds(),
            )
        except (ValueError, TypeError):
            cache_age_seconds = None


    log_cache_lookup_completed(
        request_id=getattr(
            getattr(request, "state", None), "request_id", None
        ),
        url=url,
        cache_hit=cache_hit,
        cache_layer=cache_layer,
        age_seconds=cache_age_seconds,
    )


    # --- Extraction quality normalization ---------------------------------
    
    deduplicated_count = 0
    token_truncated = False
    scrape_baseline_tokens = 0
    
    raw_text = strip_noise_lines(raw_text)
    raw_text = normalize_markdown(raw_text)
    raw_text, deduplicated_count = dedupe_blocks(raw_text)
    
    # --- Mode transformation -----------------------------------------------
    raw_tokens = count_tokens(raw_text)
    split = False
    limiting_factor = "char_cap" if content_truncated else "none"
    
    transformation_truncated = False


    if mode == "scrape":
        final_text, token_truncated = truncate_to_token_budget(
            raw_text,
            max_tokens,
        )
        chunks = [
            {
                "index": 0,
                "text": final_text,
                "approx_tokens": count_tokens(final_text),
                "tokens": count_tokens(final_text),
            }
        ]
        scrape_baseline_tokens = count_tokens(raw_text)
        approx_tokens = count_tokens(final_text)
        transformation_truncated = content_truncated or token_truncated

        if token_truncated:
            limiting_factor = "token_budget"


    elif mode == "chunk":
        chunk_strings = split_into_chunks(raw_text, max_tokens)
        chunks = [
            {
                "index": index,
                "text": chunk,
                "approx_tokens": count_tokens(chunk),
                "tokens": count_tokens(chunk),
            }
            for index, chunk in enumerate(chunk_strings)
        ]
        final_text = "\n\n---\n\n".join(chunk_strings) if chunk_strings else ""
        approx_tokens = count_tokens(final_text)
        split = len(chunk_strings) > 1
        transformation_truncated = content_truncated


    elif mode == "summarize":
        final_text, was_truncated = summarize_text(raw_text, max_tokens)
        chunks = [
            {
                "index": 0,
                "text": final_text,
                "approx_tokens": count_tokens(final_text),
                "tokens": count_tokens(final_text),
            }
        ]
        approx_tokens = count_tokens(final_text)
        transformation_truncated = content_truncated or was_truncated
        if was_truncated:
            limiting_factor = "token_budget"
    else:
        raise ValueError(f"Unknown context mode: {mode}")


    if tokens_saved_estimate is None:
        tokens_saved_estimate = max(0, html_tokens - approx_tokens)


    record_cache_tokens_saved(
        mode=mode,
        cache_hit=cache_hit,
        cache_layer=cache_layer,
        approx_tokens=approx_tokens,
        tokens_saved_estimate=tokens_saved_estimate,
    )


    # Cache economics preserve upstream extraction facts, but they must not
    # erase a mode-specific transformation result. In particular, a cached
    # page served through summarize with a smaller max_tokens budget must
    # still report that this request truncated the content.
    if cache_hit and cache_economics is not None:
        resolved_truncated = (
            cache_economics.truncated or transformation_truncated
        )
        resolved_limiting_factor = cache_economics.limiting_factor
        if limiting_factor != "none":
            resolved_limiting_factor = limiting_factor
    else:
        resolved_truncated = transformation_truncated
        resolved_limiting_factor = limiting_factor


    return ContextResult(
        mode=mode,
        text=final_text,
        approx_tokens=approx_tokens,
        html_tokens=html_tokens,
        token_method=TOKEN_METHOD,
        deduplicated_count=deduplicated_count,
        limiting_factor=resolved_limiting_factor,
        tokens=approx_tokens,
        chunk_count=len(chunks),
        cache_hit=cache_hit,
        cache_layer=cache_layer,
        chunks=chunks,
        source_url=url,
        extracted_at=resolved_extracted_at,
        tokens_saved_estimate=tokens_saved_estimate,
        truncated=resolved_truncated,
        split=split,
        request_id=None,
        fetched_at=None,
        requested_url=None,
        final_url=None,
        content_type=None,
        bytes_fetched=None,
        content_sha256=None,
        cache=None,
        extractor_version=None,
    )





