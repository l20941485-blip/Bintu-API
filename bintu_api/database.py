"""Asynchronous Supabase access for persistent scrape caching and usage counts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from bintu_api.settings import Settings

if TYPE_CHECKING:
    from supabase import AsyncClient


logger = logging.getLogger("bintu_api.database")
CACHE_TTL = timedelta(hours=24)
DATABASE_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True)
class CachedMarkdown:
    markdown: str
    truncated: bool


async def create_supabase_client(settings: Settings) -> AsyncClient | None:
    """Create a server-side client only when the private database key is configured."""
    if not settings.supabase_url or not settings.supabase_service_role_key:
        return None

    from supabase import create_async_client

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
    response = await (
        client.table("scrape_cache")
        .select("markdown,truncated")
        .eq("url", url)
        .eq("render_js", render_js)
        .eq("include_nav", include_nav)
        .eq("include_header", include_header)
        .eq("include_footer", include_footer)
        .gt("created_at", cutoff)
        .maybe_single()
        .execute()
    )
    row = response.data
    if not isinstance(row, dict):
        return None
    markdown = row.get("markdown")
    truncated = row.get("truncated", False)
    if not isinstance(markdown, str) or not isinstance(truncated, bool):
        logger.warning("supabase_cache_invalid_row")
        return None
    return CachedMarkdown(markdown=markdown, truncated=truncated)


async def upsert_cached_markdown(
    client: AsyncClient,
    url: str,
    render_js: bool,
    include_nav: bool,
    include_header: bool,
    include_footer: bool,
    markdown: str,
    truncated: bool,
) -> None:
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
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="url,render_js,include_nav,include_header,include_footer",
        )
        .execute()
    )


async def increment_developer_usage(client: AsyncClient, rapidapi_user: str) -> None:
    """Increment usage atomically via the SQL function documented in the migration."""
    await client.rpc(
        "increment_developer_usage",
        {"p_rapidapi_user": rapidapi_user},
    ).execute()
