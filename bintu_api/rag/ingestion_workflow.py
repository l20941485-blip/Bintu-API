"""Shared URL ingestion helpers and public-URL ingestion workflow."""

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


async def ingest_url_to_knowledge_core(
    request: Request,
    settings: Settings,
    url: str,
    *,
    owner_identity: str | None,
    access_labels: tuple[str, ...] = (),
    max_tokens: int = DEFAULT_INGEST_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_INGEST_OVERLAP_TOKENS,
    skip_cache: bool = False,
    extract_fn=fetch_and_extract,
    chunk_fn=split_semantic_chunks,
    chunk_repository_cls=SupabaseChunkRepository,
    ingestion_service_cls=RagIngestionService,
) -> IngestedRevision:
    """Fetch, extract, chunk, and persist a public URL into the RAG store."""
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

    document, result, _cache_layer, _revalidated = await extract_fn(
        request,
        url,
        include_nav=False,
        include_header=False,
        include_footer=False,
        render_js=False,
        links="inline",
        skip_cache=skip_cache,
        persist=True,
        mode="chunk",
        max_tokens=max_tokens,
        main_content_only=False,
    )

    source_url = sanitize_url(url)
    final_url = document.final_url if document else source_url
    chunks = chunk_fn(
        result.markdown,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
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

    repository = chunk_repository_cls(supabase_client)
    ingestion = ingestion_service_cls(repository)
    return await ingestion.ingest(
        ExtractionIngestionRequest(
            canonical_url=source_url,
            title=result.page_title,
            source_type="web",
            owner_identity=owner_identity,
            source_url=source_url,
            final_url=final_url,
            content_sha256=result.content_hash,
            content_fingerprint=result.content_fingerprint,
            extracted_at=result.extracted_at,
            language=None,
            status="active",
            chunks=chunks,
            access_labels=access_labels,
        )
    )


async def ingest_public_knowledge(
    request: Request,
    settings: Settings,
    user_id: str,
    url: str,
    *,
    max_tokens: int = DEFAULT_INGEST_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_INGEST_OVERLAP_TOKENS,
    access_labels: tuple[str, ...] = (),
    skip_cache: bool = False,
) -> IngestedRevision:
    """Fetch, extract, chunk, and persist a public page for one user."""
    return await ingest_url_to_knowledge_core(
        request,
        settings,
        url,
        owner_identity=user_id,
        access_labels=access_labels,
        max_tokens=max_tokens,
        overlap_tokens=overlap_tokens,
        skip_cache=skip_cache,
    )
