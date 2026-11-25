"""Public-URL ingestion workflow for user-owned RAG knowledge."""

from __future__ import annotations

import asyncio

from fastapi import HTTPException, Request

from bintu_api.api import scrape_adapter as routes_common
from bintu_api.api.scrape_adapter import fetch_and_extract
from bintu_api.extraction.output import sanitize_url
from bintu_api.extraction.rag_chunking import split_semantic_chunks
from bintu_api.rag.ingestion import ExtractionIngestionRequest, RagIngestionService
from bintu_api.rag.models import IngestedRevision
from bintu_api.rag.supabase import SupabaseChunkRepository
from bintu_api.settings import Settings

DEFAULT_INGEST_MAX_TOKENS = 6000
DEFAULT_INGEST_OVERLAP_TOKENS = 1200


async def ingest_public_knowledge(
    request: Request,
    settings: Settings,
    user_id: str,
    url: str,
    *,
    max_tokens: int = DEFAULT_INGEST_MAX_TOKENS,
) -> IngestedRevision:
    """Fetch, extract, chunk, and persist a public page for one user."""
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

    identity = routes_common.rate_limit_identity(request, settings)
    await asyncio.to_thread(
        request.app.state.rate_limiter.check,
        identity,
    )

    document, result, _cache_layer, _revalidated = await fetch_and_extract(
        request,
        url,
        include_nav=False,
        include_header=False,
        include_footer=False,
        render_js=False,
        links="inline",
        skip_cache=False,
        persist=True,
        mode="chunk",
        max_tokens=max_tokens,
        main_content_only=False,
    )

    source_url = sanitize_url(url)
    final_url = document.final_url if document else source_url
    chunks = split_semantic_chunks(
        result.markdown,
        max_tokens=max_tokens,
        overlap_tokens=DEFAULT_INGEST_OVERLAP_TOKENS,
        source_url=source_url,
        final_url=final_url,
        content_sha256=result.content_hash,
        extracted_at=result.extracted_at,
    )

    if not chunks:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "no_ingestable_content",
                "message": "The page did not contain ingestable readable content.",
                "hint": "Check that the target page contains extractable text or try a different URL.",
            },
        )

    repository = SupabaseChunkRepository(supabase_client)
    ingestion = RagIngestionService(repository)
    return await ingestion.ingest(
        ExtractionIngestionRequest(
            canonical_url=source_url,
            title=result.page_title,
            source_type="web",
            owner_identity=user_id,
            source_url=source_url,
            final_url=final_url,
            content_sha256=result.content_hash,
            content_fingerprint=result.content_fingerprint,
            extracted_at=result.extracted_at,
            language=None,
            status="active",
            chunks=chunks,
            access_labels=(),
        )
    )
