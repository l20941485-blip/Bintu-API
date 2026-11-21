"""Contract tests for inspecting a mobile user's RAG document."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bintu_api.api.routes.rag import router
from bintu_api.security.rate_limit import BurstRateLimiter
from bintu_api.settings import Settings


class FakeDetailRepository:
    def __init__(self, details) -> None:
        self._details = details
        self.calls = []

    async def get_document_details(
        self,
        *,
        owner_identity: str,
        document_id: str,
    ):
        self.calls.append(
            {
                "owner_identity": owner_identity,
                "document_id": document_id,
            }
        )
        return self._details


def make_client(repository: FakeDetailRepository):
    settings = Settings(
        api_key="rag-route-test-key",
        rapidapi_proxy_secret="rag-route-test-proxy",
        supabase_url="https://supabase.example",
        supabase_anon_key="anon-key",
        require_auth=True,
        rate_limit_requests=1000,
    )
    app = FastAPI()
    app.state.settings = settings
    app.state.rate_limiter = BurstRateLimiter(settings)
    app.state.supabase_client = Mock()
    app.include_router(router)

    with patch(
        "bintu_api.api.routes.rag.SupabaseDocumentDetailRepository",
        return_value=repository,
    ):
        yield TestClient(app)


def make_details():
    return {
        "document": {
            "document_id": "document-1",
            "canonical_url": "https://example.com/article",
            "title": "Example Article",
            "source_type": "web",
            "created_at": "2026-11-21T00:00:00Z",
            "updated_at": "2026-11-21T00:00:00Z",
        },
        "revision": {
            "revision_id": "revision-1",
            "source_url": "https://example.com/article",
            "final_url": "https://example.com/article",
            "extracted_at": "2026-11-21T00:00:00Z",
            "status": "active",
        },
        "chunks": [
            {
                "chunk_id": "chunk-1",
                "chunk_index": 0,
                "heading_path": ["Introduction"],
                "preview": "This article explains the product.",
            }
        ],
    }


def test_returns_document_details_for_owner():
    repository = FakeDetailRepository(make_details())

    for client in make_client(repository):
        with patch(
            "bintu_api.api.routes.rag.verify_supabase_user",
            return_value="user-1",
        ):
            response = client.get(
                "/api/v1/mobile/rag/documents/document-1",
                headers={"Authorization": "Bearer valid-session"},
            )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["document"]["document_id"] == "document-1"
    assert body["revision"]["revision_id"] == "revision-1"
    assert body["chunk_count"] == 1
    assert body["chunks"][0]["chunk_id"] == "chunk-1"
    assert body["chunks"][0]["preview"] == (
        "This article explains the product."
    )

    assert repository.calls == [
        {
            "owner_identity": "user-1",
            "document_id": "document-1",
        }
    ]


def test_returns_404_for_document_not_owned_by_user():
    repository = FakeDetailRepository(None)

    for client in make_client(repository):
        with patch(
            "bintu_api.api.routes.rag.verify_supabase_user",
            return_value="user-1",
        ):
            response = client.get(
                "/api/v1/mobile/rag/documents/document-other",
                headers={"Authorization": "Bearer valid-session"},
            )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "document_not_found"
    assert repository.calls == [
        {
            "owner_identity": "user-1",
            "document_id": "document-other",
        }
    ]
