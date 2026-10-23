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
# pulling in tiktoken or another large dependency. Named in every envelope via
# TOKEN_METHOD so callers and contracts always know what the numbers mean.
TOKEN_RE = re.compile(r"\S+")
TOKEN_METHOD = "whitespace"


def count_tokens(text: str) -> int:
    """Return an approximate token count for ``text`` (dependency-free)."""
    if not text:
        return 0
    return len(TOKEN_RE.findall(text))


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


def _decode_source_text(document: FetchedHTML) -> str:
    """Decode a fetched body for the savings baseline (best effort, no throws).

    The baseline deliberately counts the raw document — markup included — so
    `tokens_saved_estimate` is approximately " fetched HTML tokens minus
    delivered text tokens", the all-in number the cost-reduction story needs.
    """
    try:
        if document.charset:
            return document.body.decode(document.charset, errors="replace")
        return document.body.decode("utf-8", errors="replace")
    except Exception:  # pragma: no cover - decoder lookup is already guarded
        return ""


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
    cache_layer = "none"
    raw_text: str | None = None
    # Raw HTML for the all-in estimate baseline: whitespace tokens of the
    # fetched document, so `tokens_saved_estimate` measures the whole strip
    # (nav/ads/footer removal + character cap + mode trimming), not zero.
    html_source_text: str | None = None
    # True when the upstream extractor cut the document at the character cap.
    # This is content loss and must reach the caller in every mode (P1).
    content_truncated = False
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
            cache_layer = "memory"
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
            content_truncated = extracted.truncated
            html_source_text = _decode_source_text(document)

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
            skip_cache=not cache,
        )
        raw_text = scrape_result.text
        content_truncated = scrape_result.truncated
        # _scrape_text stores the fetched document in the memory cache (or
        # returns a persistent-cache row); reuse the body for the estimate
        # baseline instead of reporting zero.
        cached_document = request.app.state.cache.get(cache_key)
        if cached_document is not None:
            document = cached_document
            html_source_text = _decode_source_text(cached_document)

    if html_source_text is None:
        # Persistent-cache-only path: body gone, so the estimate degrades to
        # delivered-text-vs-delivered-text (zero) rather than inventing data.
        html_source_text = raw_text

    # --- Mode transformation -----------------------------------------------
    # tokens_saved_estimate: the whole strip, honestly measured. `html_tokens`
    # counts the whitespace tokens of the fetched HTML document; `approx_tokens`
    # counts what we actually deliver. The estimate is their difference, so it
    # includes nav/ads/footer stripping, the character cap, and any mode-level
    # trimming (never negative). Both figures use the same dependency-free
    # whitespace counter, named in `token_method` so a future tokenizer (e.g.
    # tiktoken) can be swapped in without changing the envelope shape.
    html_tokens = count_tokens(html_source_text)
    raw_tokens = count_tokens(raw_text)
    # Which cap bound the result? The character cap binds when the upstream
    # extractor cut the document; otherwise the caller's token budget binds
    # only when a mode trimmed below it (summarize dropping sentences).
    # `split` only says the text was divided across several chunks. Chunking
    # delivers every token, so it is never content loss (P2).
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
                "index": i,
                "text": c,
                "approx_tokens": count_tokens(c),
                "tokens": count_tokens(c),
            }
            for i, c in enumerate(chunk_strings)
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

    tokens_saved_estimate = max(0, html_tokens - approx_tokens)

    return ContextResult(
        mode=mode,
        text=final_text,
        approx_tokens=approx_tokens,
        html_tokens=html_tokens,
        token_method=TOKEN_METHOD,
        limiting_factor=limiting_factor,
        tokens=approx_tokens,
        chunk_count=len(chunks),
        cache_hit=cache_hit,
        chunks=chunks,
        source_url=url,
        extracted_at=datetime.now(timezone.utc).isoformat(),
        tokens_saved_estimate=tokens_saved_estimate,
        truncated=truncated,
        split=split,
    )

