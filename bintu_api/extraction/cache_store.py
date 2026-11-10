"""Supabase persistence for extracted Markdown and cache metadata."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from supabase import AsyncClient  # type: ignore[import-not-found,import-unresolved] # pyright: ignore[reportMissingImports]
else:
    # Runtime fallback so annotations (PEP 563 strings via
    # `from __future__ import annotations`) and tools that inspect
    # module attributes never raise NameError when supabase isn't installed.
    # The real client is imported lazily inside create_supabase_client().
    # Annotated as TypeAlias so Pylance/pyright accept it in type expressions
    # like `AsyncClient | None` ("Variable not allowed in type expression").
    AsyncClient: TypeAlias = Any


logger = logging.getLogger("bintu_api.database")
# Bump when extracted Markdown or its stored metadata changes.
EXTRACTOR_VERSION = "2026-10-30.1"
CACHE_TTL = timedelta(hours=24)


class CacheWriteFailed(RuntimeError):
    """Supabase accepted the request but did not return a persisted cache row."""


@dataclass(frozen=True)
class CachedMarkdown:
    markdown: str
    truncated: bool
    html_tokens: int = 0
    tokens_saved_estimate: int = 0
    limiting_factor: str = "none"
    extracted_at: str = ""


async def get_cached_markdown(
    client: AsyncClient,
    url: str,
    render_js: bool,
    include_nav: bool,
    include_header: bool,
    include_footer: bool,
) -> CachedMarkdown | None:
    """Return a cache entry only if it was successfully extracted in the last 24 hours."""
    cutoff = (datetime.now(UTC) - CACHE_TTL).isoformat()
    # Plain select + limit(1) instead of maybe_single(): maybe_single() sends
    # `Accept: application/vnd.pgrst.object+json`, which PostgREST answers with
    # 406 Not Acceptable whenever zero rows match (observed live 2026-10-17),
    # and postgrest-py returns None / a bare dict rather than an APIResponse —
    # so `response.data` raised AttributeError on every lookup. A plain select
    # returns 200 with [] for a miss, and the composite primary key on
    # (url, render_js, include_nav, include_header, include_footer) guarantees
    # at most one row per cache key.
    response = await (
        client.table("scrape_cache")
        .select("markdown,truncated,html_tokens,tokens_saved_estimate,limiting_factor,extracted_at")
        .eq("url", url)
        .eq("render_js", render_js)
        .eq("include_nav", include_nav)
        .eq("include_header", include_header)
        .eq("include_footer", include_footer)
        .eq("extractor_version", EXTRACTOR_VERSION)
        .gt("created_at", cutoff)
        .limit(1)
        .execute()
    )
    rows = response.data
    if not isinstance(rows, list) or not rows:
        return None
    row = rows[0]
    if not isinstance(row, dict):
        return None
    markdown = row.get("markdown")
    truncated = row.get("truncated", False)
    if not isinstance(markdown, str) or not markdown or not isinstance(truncated, bool):
        logger.warning("supabase_cache_invalid_row")
        return None

    html_tokens = _safe_int(row.get("html_tokens"), default=0)
    tokens_saved_estimate = _safe_int(row.get("tokens_saved_estimate"), default=0)
    limiting_factor = row.get("limiting_factor")
    extracted_at = row.get("extracted_at")

    return CachedMarkdown(
        markdown=markdown,
        truncated=truncated,
        html_tokens=html_tokens,
        tokens_saved_estimate=tokens_saved_estimate,
        limiting_factor=(limiting_factor if isinstance(limiting_factor, str) and limiting_factor else "none"),
        extracted_at=(extracted_at if isinstance(extracted_at, str) and extracted_at else ""),
    )


async def upsert_cached_markdown(
    client: AsyncClient,
    url: str,
    render_js: bool,
    include_nav: bool,
    include_header: bool,
    include_footer: bool,
    markdown: str,
    truncated: bool,
    html_tokens: int = 0,
    tokens_saved_estimate: int = 0,
    limiting_factor: str = "none",
    extracted_at: str | None = None,
) -> None:
    """Store extracted text plus the economics needed to rehydrate cache hits.



    Raises CacheWriteFailed when Supabase does not return exactly one persisted
    row. The route already catches unexpected database failures and logs them
    without exposing URL material.
    """
    if not url:
        raise ValueError("cache url is required")
    if not isinstance(markdown, str) or not markdown.strip():
        # Do not persist empty extractions: they would poison later cache hits.
        raise ValueError("refusing to cache empty extraction")

    if extracted_at is None:
        extracted_at = datetime.now(UTC).isoformat()

    response = await (
        client.table("scrape_cache")
        .upsert(
            {
                "url": url,
                "render_js": render_js,
                "include_nav": include_nav,
                "include_header": include_header,
                "include_footer": include_footer,
                "extractor_version": EXTRACTOR_VERSION,
                "markdown": markdown,
                "truncated": truncated,
                "html_tokens": max(0, int(html_tokens)),
                "tokens_saved_estimate": max(0, int(tokens_saved_estimate)),
                "limiting_factor": limiting_factor,
                "extracted_at": extracted_at,
                "created_at": datetime.now(UTC).isoformat(),
            },
            on_conflict="url,render_js,include_nav,include_header,include_footer",
        )
        .execute()
    )

    rows = getattr(response, "data", None)
    if not isinstance(rows, list) or len(rows) != 1:
        logger.warning(
            "supabase_cache_write_unverified rows_type=%s rows_count=%s",
            type(rows).__name__,
            len(rows) if isinstance(rows, list) else "not_a_list",
        )
        raise CacheWriteFailed("supabase did not return a persisted cache row")


def _safe_int(value: Any, *, default: int = 0) -> int:
    """Coerce a database value to a non-negative integer without raising."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0, int(value))
