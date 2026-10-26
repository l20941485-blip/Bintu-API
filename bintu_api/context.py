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

# Pitch-name aliases: marketing copy uses "chunked" / "chunk_token_budget"
# while the canonical protocol stays "chunk" / "max_tokens" so existing
# Claude connectors never break. Normalization is case/whitespace tolerant.
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
    """True when a Markdown block looks like a table."""
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    return len(lines) >= 2 and all(line.startswith("|") for line in lines)


def _split_oversized_table(block: str, max_tokens: int) -> list[str]:
    """Split a Markdown table without breaking an individual row."""
    lines = [line for line in block.splitlines() if line.strip()]
    if not lines:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for line in lines:
        line_tokens = count_tokens(line)
        candidate_tokens = current_tokens + line_tokens + (1 if current else 0)

        if current and candidate_tokens > max_tokens:
            chunks.append("\n".join(current))
            current = [line]
            current_tokens = line_tokens
        else:
            current.append(line)
            current_tokens = candidate_tokens

    if current:
        chunks.append("\n".join(current))

    return chunks


def _split_prose_block(block: str, max_tokens: int) -> list[str]:
    """Split a prose block by sentence, preserving punctuation."""
    if count_tokens(block) <= max_tokens:
        return [block]

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for sentence in _sentences(block):
        sentence_tokens = count_tokens(sentence)

        if current and current_tokens + sentence_tokens + 1 > max_tokens:
            chunks.append(" ".join(current))
            current = [sentence]
            current_tokens = sentence_tokens
        else:
            current.append(sentence)
            current_tokens += sentence_tokens + (1 if len(current) > 1 else 0)

    if current:
        chunks.append(" ".join(current))

    return chunks


def _split_block(block: str, max_tokens: int) -> list[str]:
    """Split one paragraph/table block without losing its internal structure."""
    if count_tokens(block) <= max_tokens:
        return [block]

    if _is_table_block(block):
        return _split_oversized_table(block, max_tokens)

    chunks = _split_prose_block(block, max_tokens)

    # A single very long sentence may still exceed the budget. Split it by
    # words, but retain spaces so downstream consumers receive readable text.
    result: list[str] = []
    for chunk in chunks:
        if count_tokens(chunk) <= max_tokens:
            result.append(chunk)
            continue

        words = chunk.split()
        current: list[str] = []
        current_tokens = 0

        for word in words:
            word_tokens = count_tokens(word)
            candidate_tokens = current_tokens + word_tokens + (
                1 if current else 0
            )

            if current and candidate_tokens > max_tokens:
                result.append(" ".join(current))
                current = [word]
                current_tokens = word_tokens
            else:
                current.append(word)
                current_tokens = candidate_tokens

        if current:
            result.append(" ".join(current))

    return result


def split_into_chunks(text: str, max_tokens: int) -> list[str]:
    """Split ``text`` into chunks of at most ``max_tokens`` tokens.

    Preserves paragraph, sentence, and Markdown-table boundaries where
    possible. No LangChain or other heavy dependency is required.
    """
    if not text:
        return []
    if max_tokens <= 0:
        return [text]

    blocks = [block.strip() for block in re.split(r"\n\s*\n", text) if block.strip()]
    if not blocks:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for block in blocks:
        block_pieces = _split_block(block, max_tokens)

        for piece in block_pieces:
            piece_tokens = count_tokens(piece)
            candidate_tokens = current_tokens + piece_tokens + (
                2 if current else 0
            )

            if current and candidate_tokens > max_tokens:
                chunks.append("\n\n".join(current))
                current = [piece]
                current_tokens = piece_tokens
            else:
                current.append(piece)
                current_tokens = candidate_tokens

    if current:
        chunks.append("\n\n".join(current))

    return chunks


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

    # --- Mode transformation -----------------------------------------------
    raw_tokens = count_tokens(raw_text)
    split = False
    limiting_factor = "char_cap" if content_truncated else "none"

    if mode == "scrape":
        final_text = raw_text
        chunks = [
            {
                "index": 0,
                "text": raw_text,
                "approx_tokens": count_tokens(raw_text),
                "tokens": count_tokens(raw_text),
            }
        ]
        approx_tokens = count_tokens(final_text)
        truncated = content_truncated

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
        truncated = content_truncated

    elif mode == "summarize":
        if count_tokens(raw_text) <= max_tokens:
            final_text = raw_text
            chunks = [
                {
                    "index": 0,
                    "text": raw_text,
                    "approx_tokens": count_tokens(raw_text),
                    "tokens": count_tokens(raw_text),
                }
            ]
            approx_tokens = count_tokens(final_text)
            truncated = content_truncated
        else:
            selected: list[str] = []
            used = 0

            for sentence in _sentences(raw_text):
                sentence_tokens = count_tokens(sentence)
                if used + sentence_tokens > max_tokens and selected:
                    break
                selected.append(sentence)
                used += sentence_tokens

            final_text = " ".join(selected)
            chunks = [
                {
                    "index": 0,
                    "text": final_text,
                    "approx_tokens": count_tokens(final_text),
                    "tokens": count_tokens(final_text),
                }
            ]
            approx_tokens = count_tokens(final_text)
            truncated = True
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

    return ContextResult(
        mode=mode,
        text=final_text,
        approx_tokens=approx_tokens,
        html_tokens=html_tokens,
        token_method=TOKEN_METHOD,
        limiting_factor=(
            cache_economics.limiting_factor
            if cache_hit and cache_economics is not None
            else limiting_factor
        ),
        tokens=approx_tokens,
        chunk_count=len(chunks),
        cache_hit=cache_hit,
        cache_layer=cache_layer,
        chunks=chunks,
        source_url=url,
        extracted_at=resolved_extracted_at,
        tokens_saved_estimate=tokens_saved_estimate,
        truncated=(
            cache_economics.truncated
            if cache_hit and cache_economics is not None
            else truncated
        ),
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