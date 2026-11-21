"""HTTP contract tests for the grounded RAG answer endpoint."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from bintu_api.api.routes.rag import router
from bintu_api.security.rate_limit import BurstRateLimiter
from bintu_api.settings import Settings

API_KEY = "rag-route-test-key"
AUTH = {"X-API-Key": API_KEY}


@pytest.fixture
def client():
    settings = Settings(
        api_key=API_KEY,
        rapidapi_proxy_secret="rag-route-test-proxy",
        require_auth=True,
        rate_limit_requests=1000,
    )
    app = FastAPI()
    app.state.settings = settings
    app.state.rate_limiter = BurstRateLimiter(settings)
    app.include_router(router)

    supabase = Mock()
    supabase.rpc = Mock(
        return_value=Mock(
            execute=AsyncMock(
                return_value=Mock(
                    data=[
                        {
                            "chunk_id": "chunk-auth",
                            "revision_id": "revision-1",
                            "document_id": "document-1",
                            "text": "## Authentication\n\nUse an API key.",
                            "score": 1.0,
                            "source_url": "https://example.com/original",
                            "final_url": "https://example.com/final",
                            "heading_path": ["Guide", "Authentication"],
                            "access_labels": ["public"],
                        }
                    ]
                )
            )
        )
    )
    app.state.supabase_client = supabase

    with TestClient(app) as test_client:
        yield test_client


def test_answer_returns_grounded_response(client):
    response = client.post(
        "/api/v1/rag/answers",
        json={
            "query": "How do I use authentication?",
            "limit": 5,
            "access_labels": ["public"],
        },
        headers=AUTH,
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == "Use an API key."
    assert body["insufficient_evidence"] is False
    assert len(body["citations"]) == 1
    assert body["citations"][0]["chunk_id"] == "chunk-auth"
    assert body["citations"][0]["heading_path"] == [
        "Guide",
        "Authentication",
    ]


def test_blank_query_is_rejected(client):
    response = client.post(
        "/api/v1/rag/answers",
        json={"query": "   "},
        headers=AUTH,
    )

    assert response.status_code == 422


def test_missing_knowledge_core_returns_503():
    settings = Settings(
        api_key=API_KEY,
        rapidapi_proxy_secret="rag-route-test-proxy",
        require_auth=True,
        rate_limit_requests=1000,
    )
    app = FastAPI()
    app.state.settings = settings
    app.state.rate_limiter = BurstRateLimiter(settings)
    app.state.supabase_client = None
    app.include_router(router)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/rag/answers",
            json={"query": "How do I use authentication?"},
            headers=AUTH,
        )

    assert response.status_code == 503
    assert (
        response.json()["detail"]["code"]
        == "knowledge_core_unavailable"
    )


@pytest.fixture
def mobile_client():
    settings = Settings(
        api_key=API_KEY,
        rapidapi_proxy_secret="rag-route-test-proxy",
        supabase_url="https://supabase.example",
        supabase_anon_key="anon-key",
        require_auth=True,
        rate_limit_requests=1000,
    )
    app = FastAPI()
    app.state.settings = settings
    app.state.rate_limiter = BurstRateLimiter(settings)
    app.include_router(router)

    supabase = Mock()
    supabase.rpc = Mock(
        return_value=Mock(
            execute=AsyncMock(
                return_value=Mock(
                    data=[
                        {
                            "chunk_id": "chunk-private",
                            "revision_id": "revision-1",
                            "document_id": "document-1",
                            "text": "Private onboarding steps.",
                            "score": 1.0,
                            "source_url": "https://example.com/original",
                            "final_url": "https://example.com/final",
                            "heading_path": ["Onboarding"],
                            "access_labels": [],
                        }
                    ]
                )
            )
        )
    )
    app.state.supabase_client = supabase

    with TestClient(app) as test_client:
        yield test_client


@patch(
    "bintu_api.api.routes.rag.verify_supabase_user",
    return_value="user-1",
)
def test_mobile_answer_uses_authenticated_owner_identity(
    verify_user,
    mobile_client,
):
    response = mobile_client.post(
        "/api/v1/mobile/rag/answers",
        json={
            "query": "What are the onboarding steps?",
            "access_labels": [],
        },
        headers={"Authorization": "Bearer valid-session"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["answer"] == "Private onboarding steps."
    assert body["citations"][0]["chunk_id"] == "chunk-private"

    mobile_client.app.state.supabase_client.rpc.assert_called_once_with(
        "search_rag_chunks",
        {
            "p_query": "What are the onboarding steps?",
            "p_limit": 5,
            "p_access_labels": [],
            "p_owner_identity": "user-1",
            "p_document_id": None,
        },
    )


@pytest.fixture
def ingestion_client():
    settings = Settings(
        api_key=API_KEY,
        rapidapi_proxy_secret="rag-route-test-proxy",
        supabase_url="https://supabase.example",
        supabase_anon_key="anon-key",
        require_auth=True,
        rate_limit_requests=1000,
    )
    app = FastAPI()
    app.state.settings = settings
    app.state.rate_limiter = BurstRateLimiter(settings)
    app.include_router(router)

    supabase = Mock()
    supabase.rpc = Mock(
        return_value=Mock(
            execute=AsyncMock(
                return_value=Mock(
                    data={
                        "revision_id": "revision-1",
                        "chunks": [
                            {
                                "chunk_id": "chunk-1",
                                "chunk_sha256": "chunk-hash-1",
                                "chunk_index": 0,
                            }
                        ],
                    }
                )
            )
        )
    )
    app.state.supabase_client = supabase

    with TestClient(app) as test_client:
        yield test_client


@patch(
    "bintu_api.api.routes.rag.verify_supabase_user",
    return_value="user-1",
)
@patch(
    "bintu_api.api.routes.rag.fetch_and_extract",
    new_callable=AsyncMock,
)
def test_mobile_ingest_persists_owner_knowledge(
    fetch,
    verify_user,
    ingestion_client,
):
    fetched = Mock()
    fetched.final_url = "https://example.com/final"
    result = Mock(
        markdown="# Guide\n\nIntroduction.",
        content_hash="sha256:content",
        content_fingerprint="sha256:fingerprint",
        extracted_at="2026-11-21T00:00:00+00:00",
        page_title="Example Documentation",
    )
    fetch.return_value = (fetched, result, "none", False)

    response = ingestion_client.post(
        "/api/v1/mobile/rag/ingest",
        json={
            "url": "https://example.com/docs",
            "max_tokens": 1000,
            "overlap_tokens": 0,
            "access_labels": [],
        },
        headers={"Authorization": "Bearer valid-session"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["revision_id"] == "revision-1"
    assert body["chunk_count"] == 1
    assert body["chunks"][0]["chunk_id"] == "chunk-1"

    ingestion_client.app.state.supabase_client.rpc.assert_called_once()
    arguments = (
        ingestion_client.app.state.supabase_client.rpc.call_args.args[1]
    )
    assert arguments["p_document"]["owner_identity"] == "user-1"
    assert arguments["p_chunks"][0]["access_labels"] == []


def test_api_key_answer_does_not_request_owner_knowledge(client):
    response = client.post(
        "/api/v1/rag/answers",
        json={
            "query": "How do I use authentication?",
            "limit": 5,
            "access_labels": ["public"],
        },
        headers=AUTH,
    )

    assert response.status_code == 200, response.text

    client.app.state.supabase_client.rpc.assert_called_once_with(
        "search_rag_chunks",
        {
            "p_query": "How do I use authentication?",
            "p_limit": 5,
            "p_access_labels": ["public"],
            "p_owner_identity": None,
            "p_document_id": None,
        },
    )
