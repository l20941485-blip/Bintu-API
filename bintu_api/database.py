"""Asynchronous Supabase access for persistent scrape caching and usage counts."""


from __future__ import annotations


import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, TypeAlias


from bintu_api.settings import Settings


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
CACHE_TTL = timedelta(hours=24)
DATABASE_TIMEOUT_SECONDS = 2.0



@dataclass(frozen=True)
class CachedMarkdown:
    markdown: str
    truncated: bool
    html_tokens: int = 0
    tokens_saved_estimate: int = 0
    limiting_factor: str = "none"
    extracted_at: str = ""



async def create_supabase_client(settings: Settings) -> AsyncClient | None:
    """Create a server-side client only when the private database key is configured."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None


    try:
        from supabase import create_async_client  # type: ignore[import-not-found,import-unresolved] # pyright: ignore[reportMissingImports]
    except ImportError as exc:
        raise RuntimeError(
            "supabase package is not installed. Install it with `pip install supabase==2.15.0`."
        ) from exc


    return await create_async_client(settings.supabase_url, settings.supabase_service_role_key)



async def close_supabase_client(client: AsyncClient) -> None:
    await client.aclose()



async def get_cached_markdown(
    client: AsyncClient,
    url: str,
    render_js: bool,
    include_nav: bool,
    include_header: bool,
    include_footer: bool,
) -> CachedMarkdown | None:
    """Return a cache entry only if it was successfully extracted in the last 24 hours."""
    cutoff = (datetime.now(timezone.utc) - CACHE_TTL).isoformat()
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
        .select(
            "markdown,truncated,html_tokens,tokens_saved_estimate,"
            "limiting_factor,extracted_at"
        )
        .eq("url", url)
        .eq("render_js", render_js)
        .eq("include_nav", include_nav)
        .eq("include_header", include_header)
        .eq("include_footer", include_footer)
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
    if not isinstance(markdown, str) or not isinstance(truncated, bool):
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
        limiting_factor=(
            limiting_factor
            if isinstance(limiting_factor, str) and limiting_factor
            else "none"
        ),
        extracted_at=(
            extracted_at
            if isinstance(extracted_at, str) and extracted_at
            else ""
        ),
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
    """Store extracted text plus the economics needed to rehydrate cache hits."""
    if extracted_at is None:
        extracted_at = datetime.now(timezone.utc).isoformat()


    await (
        client.table("scrape_cache")
        .upsert(
            {
                "url": url,
                "render_js": render_js,
                "include_nav": include_nav,
                "include_header": include_header,
                "include_footer": include_footer,
                "markdown": markdown,
                "truncated": truncated,
                "html_tokens": max(0, int(html_tokens)),
                "tokens_saved_estimate": max(0, int(tokens_saved_estimate)),
                "limiting_factor": limiting_factor,
                "extracted_at": extracted_at,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="url,render_js,include_nav,include_header,include_footer",
        )
        .execute()
    )



def _safe_int(value: Any, *, default: int = 0) -> int:
    """Coerce a database value to a non-negative integer without raising."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(0, int(value))



async def increment_developer_usage(client: AsyncClient, rapidapi_user: str) -> None:
    """Increment usage atomically via the SQL function documented in the migration."""
    await client.rpc(
        "increment_developer_usage",
        {"p_rapidapi_user": rapidapi_user},
    ).execute()



async def increment_token_usage(
    client: AsyncClient, rapidapi_user: str, tokens: int = 1, mode: str = "scrape"
) -> None:
    """Count one billable MCP execution with its token volume.


    Fire-and-forget with a 2s timeout at the call site (never blocks
    extraction); counts even cache hits so dashboards can bill per token
    slice. No tier caps enforced here — marketplaces own quota.
    """
    await client.rpc(
        "increment_developer_usage",
        {"p_rapidapi_user": rapidapi_user, "p_tokens": max(0, int(tokens)), "p_mode": mode},
    ).execute()