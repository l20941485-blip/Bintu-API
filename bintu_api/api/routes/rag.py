"""Grounded RAG answer endpoint for the Bintu API."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, Security

from bintu_api.api import scrape_adapter as routes_common
from bintu_api.api.schemas import (
    ErrorResponse,
    MobileRagAnswerRequest,
    MobileRagChunkPreview,
    MobileRagDocument,
    MobileRagDocumentDeleteResponse,
    MobileRagDocumentDetailResponse,
    MobileRagDocumentMetadata,
    MobileRagDocumentRefreshRequest,
    MobileRagDocumentsResponse,
    MobileRagIngestedChunk,
    MobileRagIngestRequest,
    MobileRagIngestResponse,
    MobileRagRevisionMetadata,
    RagAnswerCitation,
    RagAnswerRequest,
    RagAnswerResponse,
    RagDocsAnswerRequest,
    RagDocsIngestRequest,
)
from bintu_api.api.scrape_adapter import fetch_and_extract
from bintu_api.extraction.output import sanitize_url
from bintu_api.extraction.rag_chunking import split_semantic_chunks
from bintu_api.rag.answer import RagAnswerService
from bintu_api.rag.ingestion import ExtractionIngestionRequest, RagIngestionService
from bintu_api.rag.retrieval import RagRetrievalService
from bintu_api.rag.supabase import (
    SupabaseChunkRepository,
    SupabaseDocumentDeletionRepository,
    SupabaseDocumentDetailRepository,
    SupabaseDocumentRepository,
)
from bintu_api.rag.supabase_retrieval import SupabaseRetrievalRepository
from bintu_api.security.auth import api_key_scheme, bearer_scheme, verify_supabase_user

router = APIRouter(tags=["RAG"])


@router.post(
    "/api/v1/rag/answers",
    response_model=RagAnswerResponse,
    summary="Answer a question from retrieved knowledge",
    description=(
        "Retrieves authorized knowledge chunks and returns a grounded, "
        "extractive answer with chunk-level citations."
    ),
    responses={
        status_code: {"model": ErrorResponse}
        for status_code in (400, 401, 403, 422, 429, 503)
    },
    dependencies=[Security(api_key_scheme, scopes=[])],
)
async def answer_question(
    request: Request,
    payload: RagAnswerRequest,
) -> RagAnswerResponse:
    settings = request.app.state.settings
    routes_common.verify_api_access(request, settings)

    supabase_client = getattr(request.app.state, "supabase_client", None)
    if supabase_client is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "knowledge_core_unavailable",
                "message": "The knowledge core is not configured.",
            },
        )

    identity = routes_common.rate_limit_identity(request, settings)
    await asyncio.to_thread(
        request.app.state.rate_limiter.check,
        identity,
    )

    repository = SupabaseRetrievalRepository(supabase_client)
    retrieval = RagRetrievalService(repository)
    answer_service = RagAnswerService(retrieval)

    answer = await answer_service.answer(
        query=payload.query,
        limit=payload.limit,
        access_labels=tuple(payload.access_labels),
    )

    return RagAnswerResponse(
        answer=answer.answer,
        insufficient_evidence=answer.insufficient_evidence,
        citations=[
            RagAnswerCitation(
                chunk_id=citation.chunk_id,
                revision_id=citation.revision_id,
                document_id=citation.document_id,
                source_url=citation.source_url,
                final_url=citation.final_url,
                heading_path=list(citation.heading_path),
            )
            for citation in answer.citations
        ],
    )


@router.post(
    "/api/v1/mobile/rag/answers",
    response_model=RagAnswerResponse,
    summary="Answer a question from a signed-in user's knowledge",
    description=(
        "Requires an Authorization Bearer token from the configured Supabase "
        "project. Returns public knowledge and knowledge owned by the "
        "authenticated user, with chunk-level citations."
    ),
    responses={
        status_code: {"model": ErrorResponse}
        for status_code in (400, 401, 403, 422, 429, 503)
    },
    dependencies=[Security(bearer_scheme, scopes=[])],
)
async def mobile_answer_question(
    request: Request,
    payload: MobileRagAnswerRequest,
) -> RagAnswerResponse:
    settings = request.app.state.settings
    user_id = await asyncio.to_thread(
        verify_supabase_user,
        request,
        settings,
    )

    supabase_client = getattr(request.app.state, "supabase_client", None)
    if supabase_client is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "knowledge_core_unavailable",
                "message": "The knowledge core is not configured.",
            },
        )

    identity = routes_common.rate_limit_identity(request, settings)
    await asyncio.to_thread(
        request.app.state.rate_limiter.check,
        identity,
    )

    repository = SupabaseRetrievalRepository(supabase_client)
    retrieval = RagRetrievalService(repository)
    answer_service = RagAnswerService(retrieval)

    answer = await answer_service.answer(
        query=payload.query,
        limit=payload.limit,
        access_labels=tuple(payload.access_labels),
        owner_identity=user_id,
        document_id=payload.document_id,
    )

    return RagAnswerResponse(
        answer=answer.answer,
        insufficient_evidence=answer.insufficient_evidence,
        citations=[
            RagAnswerCitation(
                chunk_id=citation.chunk_id,
                revision_id=citation.revision_id,
                document_id=citation.document_id,
                source_url=citation.source_url,
                final_url=citation.final_url,
                heading_path=list(citation.heading_path),
            )
            for citation in answer.citations
        ],
    )


@router.post(
    "/api/v1/mobile/rag/ingest",
    response_model=MobileRagIngestResponse,
    summary="Ingest a public web page into the signed-in user's knowledge core",
    description=(
        "Fetches a public page, extracts readable content, creates semantic "
        "chunks, and persists an immutable revision for the authenticated user."
    ),
    responses={
        status_code: {"model": ErrorResponse}
        for status_code in (400, 401, 403, 422, 429, 502, 503, 504)
    },
    dependencies=[Security(bearer_scheme, scopes=[])],
)
async def mobile_ingest_knowledge(
    request: Request,
    payload: MobileRagIngestRequest,
) -> MobileRagIngestResponse:
    settings = request.app.state.settings
    user_id = await asyncio.to_thread(
        verify_supabase_user,
        request,
        settings,
    )

    supabase_client = getattr(request.app.state, "supabase_client", None)
    if supabase_client is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "knowledge_core_unavailable",
                "message": "The knowledge core is not configured.",
            },
        )

    identity = routes_common.rate_limit_identity(request, settings)
    await asyncio.to_thread(
        request.app.state.rate_limiter.check,
        identity,
    )

    document, result, _cache_layer, _revalidated = await fetch_and_extract(
        request,
        payload.url,
        include_nav=False,
        include_header=False,
        include_footer=False,
        render_js=False,
        links="inline",
        skip_cache=False,
        persist=True,
        mode="chunk",
        max_tokens=payload.max_tokens,
        main_content_only=False,
    )

    source_url = sanitize_url(payload.url)
    final_url = document.final_url if document else source_url
    chunks = split_semantic_chunks(
        result.markdown,
        max_tokens=payload.max_tokens,
        overlap_tokens=payload.overlap_tokens,
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
            },
        )

    repository = SupabaseChunkRepository(supabase_client)
    ingestion = RagIngestionService(repository)
    ingested = await ingestion.ingest(
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
            access_labels=tuple(payload.access_labels),
        )
    )

    return MobileRagIngestResponse(
        document_id=ingested.document.document_id,
        revision_id=ingested.revision_id,
        chunk_count=len(ingested.chunks),
        chunks=[
            MobileRagIngestedChunk(
                chunk_id=chunk.chunk_id or "",
                chunk_index=chunk.chunk_index,
                chunk_sha256=chunk.chunk_sha256 or "",
            )
            for chunk in ingested.chunks
        ],
    )


@router.post(
    "/api/v1/rag/docs/answers",
    response_model=RagAnswerResponse,
    summary="Answer a question from Bintu documentation",
    description=(
        "Retrieves authorized Bintu documentation chunks and returns a "
        "grounded, extractive answer with chunk-level citations."
    ),
    responses={
        status_code: {"model": ErrorResponse}
        for status_code in (400, 401, 403, 422, 429, 503)
    },
    dependencies=[Security(api_key_scheme, scopes=[])],
)
async def answer_documentation_question(
    request: Request,
    payload: RagDocsAnswerRequest,
) -> RagAnswerResponse:
    settings = request.app.state.settings
    routes_common.verify_api_access(request, settings)

    supabase_client = getattr(request.app.state, "supabase_client", None)
    if supabase_client is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "knowledge_core_unavailable",
                "message": "The knowledge core is not configured.",
            },
        )

    identity = routes_common.rate_limit_identity(request, settings)
    await asyncio.to_thread(
        request.app.state.rate_limiter.check,
        identity,
    )

    repository = SupabaseRetrievalRepository(supabase_client)
    retrieval = RagRetrievalService(repository)
    answer_service = RagAnswerService(retrieval)

    answer = await answer_service.answer(
        query=payload.query,
        limit=payload.limit,
        access_labels=("docs",),
    )

    return RagAnswerResponse(
        answer=answer.answer,
        insufficient_evidence=answer.insufficient_evidence,
        citations=[
            RagAnswerCitation(
                chunk_id=citation.chunk_id,
                revision_id=citation.revision_id,
                document_id=citation.document_id,
                source_url=citation.source_url,
                final_url=citation.final_url,
                heading_path=list(citation.heading_path),
            )
            for citation in answer.citations
        ],
    )


@router.post(
    "/api/v1/rag/docs/ingest",
    response_model=MobileRagIngestResponse,
    summary="Ingest a public documentation page into the docs collection",
    description=(
        "Fetches a public documentation page, extracts readable content, "
        "creates semantic chunks, and persists an immutable revision in the "
        "docs knowledge collection."
    ),
    responses={
        status_code: {"model": ErrorResponse}
        for status_code in (400, 401, 403, 422, 429, 502, 503, 504)
    },
    dependencies=[Security(api_key_scheme, scopes=[])],
)
async def ingest_documentation(
    request: Request,
    payload: RagDocsIngestRequest,
) -> MobileRagIngestResponse:
    settings = request.app.state.settings
    routes_common.verify_api_access(request, settings)

    supabase_client = getattr(request.app.state, "supabase_client", None)
    if supabase_client is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "knowledge_core_unavailable",
                "message": "The knowledge core is not configured.",
            },
        )

    identity = routes_common.rate_limit_identity(request, settings)
    await asyncio.to_thread(
        request.app.state.rate_limiter.check,
        identity,
    )

    document, result, _cache_layer, _revalidated = await fetch_and_extract(
        request,
        payload.url,
        include_nav=False,
        include_header=False,
        include_footer=False,
        render_js=False,
        links="inline",
        skip_cache=False,
        persist=True,
        mode="chunk",
        max_tokens=payload.max_tokens,
        main_content_only=False,
    )

    source_url = sanitize_url(payload.url)
    final_url = document.final_url if document else source_url
    chunks = split_semantic_chunks(
        result.markdown,
        max_tokens=payload.max_tokens,
        overlap_tokens=payload.overlap_tokens,
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
            },
        )

    repository = SupabaseChunkRepository(supabase_client)
    ingestion = RagIngestionService(repository)
    ingested = await ingestion.ingest(
        ExtractionIngestionRequest(
            canonical_url=source_url,
            title=result.page_title,
            source_type="web",
            owner_identity=None,
            source_url=source_url,
            final_url=final_url,
            content_sha256=result.content_hash,
            content_fingerprint=result.content_fingerprint,
            extracted_at=result.extracted_at,
            language=None,
            status="active",
            chunks=chunks,
            access_labels=("docs",),
        )
    )

    return MobileRagIngestResponse(
        document_id=ingested.document.document_id,
        revision_id=ingested.revision_id,
        chunk_count=len(ingested.chunks),
        chunks=[
            MobileRagIngestedChunk(
                chunk_id=chunk.chunk_id or "",
                chunk_index=chunk.chunk_index,
                chunk_sha256=chunk.chunk_sha256 or "",
            )
            for chunk in ingested.chunks
        ],
    )


@router.get(
    "/api/v1/mobile/rag/documents",
    response_model=MobileRagDocumentsResponse,
    summary="List the signed-in user's knowledge documents",
    description=(
        "Returns a paginated list of knowledge documents owned by the "
        "authenticated Supabase user."
    ),
    responses={
        status_code: {"model": ErrorResponse}
        for status_code in (401, 403, 429, 503)
    },
    dependencies=[Security(bearer_scheme, scopes=[])],
)
async def list_mobile_rag_documents(
    request: Request,
    limit: int = 20,
    offset: int = 0,
) -> MobileRagDocumentsResponse:
    settings = request.app.state.settings
    user_id = await asyncio.to_thread(
        verify_supabase_user,
        request,
        settings,
    )

    supabase_client = getattr(request.app.state, "supabase_client", None)
    if supabase_client is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "knowledge_core_unavailable",
                "message": "The knowledge core is not configured.",
            },
        )

    identity = routes_common.rate_limit_identity(request, settings)
    await asyncio.to_thread(
        request.app.state.rate_limiter.check,
        identity,
    )

    if limit < 1 or limit > 100:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_limit",
                "message": "limit must be between 1 and 100.",
            },
        )

    if offset < 0:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_offset",
                "message": "offset must not be negative.",
            },
        )

    repository = SupabaseDocumentRepository(supabase_client)
    documents, total = await repository.list_documents(
        owner_identity=user_id,
        limit=limit,
        offset=offset,
    )

    return MobileRagDocumentsResponse(
        documents=[
            MobileRagDocument(
                document_id=document.document_id,
                canonical_url=document.canonical_url,
                title=document.title,
                source_type=document.source_type,
                created_at=document.created_at,
                updated_at=document.updated_at,
                revision_count=document.revision_count,
            )
            for document in documents
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete(
    "/api/v1/mobile/rag/documents/{document_id}",
    response_model=MobileRagDocumentDeleteResponse,
    summary="Delete a signed-in user's knowledge document",
    description=(
        "Deletes a knowledge document owned by the authenticated Supabase "
        "user, including its revisions and chunks."
    ),
    responses={
        status_code: {"model": ErrorResponse}
        for status_code in (401, 403, 404, 429, 503)
    },
    dependencies=[Security(bearer_scheme, scopes=[])],
)
async def delete_mobile_rag_document(
    request: Request,
    document_id: str,
) -> MobileRagDocumentDeleteResponse:
    settings = request.app.state.settings
    user_id = await asyncio.to_thread(
        verify_supabase_user,
        request,
        settings,
    )

    supabase_client = getattr(request.app.state, "supabase_client", None)
    if supabase_client is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "knowledge_core_unavailable",
                "message": "The knowledge core is not configured.",
            },
        )

    identity = routes_common.rate_limit_identity(request, settings)
    await asyncio.to_thread(
        request.app.state.rate_limiter.check,
        identity,
    )

    repository = SupabaseDocumentDeletionRepository(supabase_client)
    deleted = await repository.delete_document(
        owner_identity=user_id,
        document_id=document_id,
    )

    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "document_not_found",
                "message": "The requested knowledge document was not found.",
            },
        )

    return MobileRagDocumentDeleteResponse(
        document_id=document_id,
        deleted=True,
    )


@router.get(
    "/api/v1/mobile/rag/documents/{document_id}",
    response_model=MobileRagDocumentDetailResponse,
    summary="Get a signed-in user's knowledge document",
    description=(
        "Returns metadata and bounded chunk previews for a knowledge "
        "document owned by the authenticated Supabase user."
    ),
    responses={
        status_code: {"model": ErrorResponse}
        for status_code in (401, 403, 404, 429, 503)
    },
    dependencies=[Security(bearer_scheme, scopes=[])],
)
async def get_mobile_rag_document(
    request: Request,
    document_id: str,
) -> MobileRagDocumentDetailResponse:
    settings = request.app.state.settings
    user_id = await asyncio.to_thread(
        verify_supabase_user,
        request,
        settings,
    )

    supabase_client = getattr(request.app.state, "supabase_client", None)
    if supabase_client is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "knowledge_core_unavailable",
                "message": "The knowledge core is not configured.",
            },
        )

    identity = routes_common.rate_limit_identity(request, settings)
    await asyncio.to_thread(
        request.app.state.rate_limiter.check,
        identity,
    )

    repository = SupabaseDocumentDetailRepository(supabase_client)
    details = await repository.get_document_details(
        owner_identity=user_id,
        document_id=document_id,
    )

    if not details:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "document_not_found",
                "message": "The requested knowledge document was not found.",
            },
        )

    document = details["document"]
    revision = details["revision"]
    chunks = details.get("chunks", [])

    return MobileRagDocumentDetailResponse(
        document=MobileRagDocumentMetadata(
            document_id=document["document_id"],
            canonical_url=document["canonical_url"],
            title=document.get("title"),
            source_type=document["source_type"],
            created_at=document["created_at"],
            updated_at=document["updated_at"],
        ),
        revision=MobileRagRevisionMetadata(
            revision_id=revision["revision_id"],
            source_url=revision["source_url"],
            final_url=revision.get("final_url"),
            extracted_at=revision["extracted_at"],
            status=revision["status"],
        ),
        chunk_count=len(chunks),
        chunks=[
            MobileRagChunkPreview(
                chunk_id=chunk["chunk_id"],
                chunk_index=chunk["chunk_index"],
                heading_path=chunk.get("heading_path") or [],
                preview=chunk["preview"],
            )
            for chunk in chunks
        ],
    )


@router.post(
    "/api/v1/mobile/rag/documents/{document_id}/refresh",
    response_model=MobileRagIngestResponse,
    summary="Refresh a signed-in user's knowledge document",
    description=(
        "Re-fetches the document's canonical URL, extracts current content, "
        "creates a new immutable revision, and replaces the active chunk set."
    ),
    responses={
        status_code: {"model": ErrorResponse}
        for status_code in (401, 403, 404, 422, 429, 502, 503, 504)
    },
    dependencies=[Security(bearer_scheme, scopes=[])],
)
async def refresh_mobile_rag_document(
    request: Request,
    document_id: str,
    payload: MobileRagDocumentRefreshRequest,
) -> MobileRagIngestResponse:
    settings = request.app.state.settings
    user_id = await asyncio.to_thread(
        verify_supabase_user,
        request,
        settings,
    )

    supabase_client = getattr(request.app.state, "supabase_client", None)
    if supabase_client is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "knowledge_core_unavailable",
                "message": "The knowledge core is not configured.",
            },
        )

    identity = routes_common.rate_limit_identity(request, settings)
    await asyncio.to_thread(
        request.app.state.rate_limiter.check,
        identity,
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
            },
        )

    canonical_url = details["document"]["canonical_url"]

    document, result, _cache_layer, _revalidated = await fetch_and_extract(
        request,
        canonical_url,
        include_nav=False,
        include_header=False,
        include_footer=False,
        render_js=False,
        links="inline",
        skip_cache=False,
        persist=True,
        mode="chunk",
        max_tokens=payload.max_tokens,
        main_content_only=False,
    )

    source_url = sanitize_url(canonical_url)
    final_url = document.final_url if document else source_url
    chunks = split_semantic_chunks(
        result.markdown,
        max_tokens=payload.max_tokens,
        overlap_tokens=payload.overlap_tokens,
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
            },
        )

    repository = SupabaseChunkRepository(supabase_client)
    ingestion = RagIngestionService(repository)
    ingested = await ingestion.ingest(
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
            access_labels=tuple(payload.access_labels),
        )
    )

    return MobileRagIngestResponse(
        document_id=ingested.document.document_id,
        revision_id=ingested.revision_id,
        chunk_count=len(ingested.chunks),
        chunks=[
            MobileRagIngestedChunk(
                chunk_id=chunk.chunk_id or "",
                chunk_index=chunk.chunk_index,
                chunk_sha256=chunk.chunk_sha256 or "",
            )
            for chunk in ingested.chunks
        ],
    )
