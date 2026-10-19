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
import hashlib
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import Request

from bintu_api.auth import rate_limit_identity
from bintu_api.cache import TTLCache
from bintu_api.routes import _scrape_text
from bintu_api.scraper import FetchedHTML, extract_text_result
from bintu_api.settings import Settings

logger = logging.getLogger("bintu_api.context")

ContextMode = Literal["scrape", "chunk", "summarize"]

# Pitch-name aliases: marketing copy uses "chunked" / "chunk_token_budget"
# while the canonical protocol stays "chunk" / "max_tokens" so existing
# Claude connectors never break. Normalization is case/whitespace tolerant.
MODE_ALIASES = {"chunked": "chunk"}


def normalize_mode(value: Any) -> str:
    """Normalize a mode value to its canonical form (case/whitespace tolerant)."""
    if not isinstance(value, str):
        return value  # type: ignore[return-value]
    cleaned = value.strip().lower()
    return MODE_ALIASES.get(cleaned, cleaned)

# Dependency-free approximate tokenizer: split on whitespace sequences.
# Good enough (~1 token per English word) for RAG sizing estimates without
# pulling in tiktoken or another large dependency.
TOKEN_RE = re.compile(r"\S+")


def count_tokens(text: str) -> int:
    """Return an approximate token count for ``text`` (dependency-free)."""
    if not text:
        return 0
    return len(TOKEN_RE.findall(text))


@dataclass(frozen=True)
class ContextResult:
    mode: ContextMode
    text: str
    tokens: int
    chunk_count: int
    cache_hit: bool
    chunks: list[dict[str, Any]]
    source_url: str
    extracted_at: str
    tokens_saved_estimate: int = 0
    truncated: bool = False


def split_into_chunks(text: str, max_tokens: int) -> list[str]:
    """Split ``text`` into chunks of at most ``max_tokens`` tokens.

    Preserves paragraph and sentence boundaries where possible using a
    recursive separator strategy. No LangChain or other heavy dependency
    required.
    """
    if not text:
        return []
    if max_tokens <= 0:
        return [text]

    separators = ["\n\n", "\n", ". ", "! ", "? ", "; ", ", ", " ", ""]

    def _split(text: str, sep_index: int) -> list[str]:
        if sep_index >= len(separators):
            # Last resort: hard split by token count.
            tokens = TOKEN_RE.findall(text)
            return [
                " ".join(tokens[i : i + max_tokens])
                for i in range(0, len(tokens), max_tokens)
            ]

        sep = separators[sep_index]
        parts = text.split(sep) if sep else list(text)
        chunks: list[str] = []
        current = ""

        for part in parts:
            candidate = (current + sep + part) if current else part
            if count_tokens(candidate) <= max_tokens:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                sub_chunks = _split(part, sep_index + 1)
                chunks.extend(sub_chunks)
                current = ""

        if current:
            chunks.append(current)
        return chunks

    return _split(text, 0)


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
    settings: Settings | None = None,
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

    cache_key = hashlib.sha256(f"{int(render_js)}:{url}".encode()).hexdigest()
    cache_hit = False
    raw_text: str | None = None
    # Canonicalize pitch-name aliases up front so the cache key + downstream
    # logic always operate on canonical values.
    mode = normalize_mode(mode)  # type: ignore[assignment]
    if mode not in ("scrape", "chunk", "summarize"):
        raise ValueError(f"Unknown context mode: {mode}")

    # --- Memory-cache read -------------------------------------------------
    document: FetchedHTML | None = None
    if cache:
        document = request.app.state.cache.get(cache_key)
        if document is not None:
            cache_hit = True
            extracted = extract_text_result(
                document.body,
                settings.max_text_characters,
                include_nav=include_nav,
                include_header=include_header,
                include_footer=include_footer,
                from_encoding=document.charset,
                base_url=document.final_url or url,
            )
            raw_text = extracted.text

    # --- Fetch + extract via the existing pipeline -------------------------
    if raw_text is None:
        # _scrape_text handles rate limiting, Supabase cache, fetch, extract,
        # memory-cache store, and Supabase upsert — all existing guards intact.
        scrape_result = await _scrape_text(
            request,
            url,
            include_nav=include_nav,
            include_header=include_header,
            include_footer=include_footer,
            identity=identity,
            render_js=render_js,
        )
        raw_text = scrape_result.text

    # --- Mode transformation -----------------------------------------------
    # tokens_saved_estimate: nav/ads/footer stripping already happened in
    # _scrape_text; estimate savings as raw tokens minus delivered tokens.
    # This is an approximate whitespace-token delta for cost-reduction copy.
    raw_tokens = count_tokens(raw_text)
    if mode == "scrape":
        final_text = raw_text
        chunks = [{"index": 0, "text": raw_text, "tokens": count_tokens(raw_text)}]
        tokens = count_tokens(final_text)
        truncated = False
    elif mode == "chunk":
        chunk_strings = split_into_chunks(raw_text, max_tokens)
        chunks = [
            {"index": i, "text": c, "tokens": count_tokens(c)}
            for i, c in enumerate(chunk_strings)
        ]
        final_text = "\n\n---\n\n".join(chunk_strings) if chunk_strings else ""
        tokens = count_tokens(final_text)
        truncated = tokens >= max_tokens and len(chunk_strings) > 1
    elif mode == "summarize":
        if count_tokens(raw_text) <= max_tokens:
            final_text = raw_text
            chunks = [{"index": 0, "text": raw_text, "tokens": count_tokens(raw_text)}]
            tokens = count_tokens(final_text)
            truncated = False
        else:
            sentences = re.split(r"(?<=[.!?])\s+", raw_text)
            selected: list[str] = []
            used = 0
            for sentence in sentences:
                sentence_tokens = count_tokens(sentence)
                if used + sentence_tokens > max_tokens and selected:
                    break
                selected.append(sentence)
                used += sentence_tokens
            final_text = " ".join(selected)
            chunks = [{"index": 0, "text": final_text, "tokens": count_tokens(final_text)}]
            tokens = count_tokens(final_text)
            truncated = True
    else:
        raise ValueError(f"Unknown context mode: {mode}")

    tokens_saved_estimate = max(0, raw_tokens - tokens)

    return ContextResult(
        mode=mode,
        text=final_text,
        tokens=tokens,
        chunk_count=len(chunks),
        cache_hit=cache_hit,
        chunks=chunks,
        source_url=url,
        extracted_at=datetime.now(timezone.utc).isoformat(),
        tokens_saved_estimate=tokens_saved_estimate,
        truncated=truncated,
    )

