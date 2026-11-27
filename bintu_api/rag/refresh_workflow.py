"""Refresh workflow for a user-owned RAG knowledge document."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException, Request

from bintu_api.api import scrape_adapter as routes_common
from bintu_api.rag.ingestion_workflow import (
    DEFAULT_INGEST_MAX_TOKENS,
    DEFAULT_INGEST_OVERLAP_TOKENS,
    ingest_url_to_knowledge_core,
)
from bintu_api.rag.models import IngestedRevision
from bintu_api.rag.supabase import SupabaseDocumentDetailRepository
from bintu_api.settings import Settings

DEFAULT_REFRESH_MAX_TOKENS = DEFAULT_INGEST_MAX_TOKENS
DEFAULT_REFRESH_OVERLAP_TOKENS = DEFAULT_INGEST_OVERLAP_TOKENS


async def refresh_user_knowledge(
    request: Request,
    settings: Settings,
    user_id: str,
    document_id: str,
    *,
    skip_cache: bool = False,
) -> IngestedRevision:
    """Refresh one user-owned document using its stored canonical URL."""
    supabase_client = getattr(request.app.state, "supabase_client", None)
    if supabase_client is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "knowledge_core_unavailable",
                "message": "The knowledge core is not configured.",
                "hint": "Verify Supabase and knowledge store configuration before retrying.",
            },
        )

    detail_repository = SupabaseDocumentDetailRepository(supabase_client)
    details = await detail_repository.get_document_details(
        owner_identity=user_id,
        document_id=document_id,
    )

    if not details:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "document_not_found",
                "message": "The requested knowledge document was not found.",
                "hint": "Verify the document_id or list stored documents first.",
            },
        )

    canonical_url = (details["document"].get("canonical_url") or "").strip()
    if not canonical_url:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_document_source",
                "message": "The stored knowledge document is missing a valid canonical URL.",
                "hint": "Re-ingest the document from a valid source URL.",
            },
        )

    rate_limiter = getattr(request.app.state, "rate_limiter", None)
    if rate_limiter is not None:
        identity = routes_common.rate_limit_identity(request, settings)
        await asyncio.to_thread(
            rate_limiter.check,
            identity,
        )

    return await ingest_url_to_knowledge_core(
        request,
        settings,
        canonical_url,
        owner_identity=user_id,
        access_labels=(),
        max_tokens=DEFAULT_REFRESH_MAX_TOKENS,
        overlap_tokens=DEFAULT_REFRESH_OVERLAP_TOKENS,
        skip_cache=skip_cache,
    )
