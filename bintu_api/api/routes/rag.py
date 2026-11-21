"""Grounded RAG answer endpoint for the Bintu API."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request, Security

from bintu_api.api import scrape_adapter as routes_common
from bintu_api.api.schemas import (
    ErrorResponse,
    RagAnswerCitation,
    RagAnswerRequest,
    RagAnswerResponse,
)
from bintu_api.rag.answer import RagAnswerService
from bintu_api.rag.retrieval import RagRetrievalService
from bintu_api.rag.supabase_retrieval import SupabaseRetrievalRepository
from bintu_api.security.auth import api_key_scheme

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
