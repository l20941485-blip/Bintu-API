"""Contract tests for listing a mobile user's RAG documents."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bintu_api.api.routes.rag import router
from bintu_api.security.rate_limit import BurstRateLimiter
from bintu_api.settings import Settings


class FakeDocumentRepository:
    def __init__(self) -> None:
        self.calls = []

    async def list_documents(
        self,
        *,
        owner_identity: str,
        limit: int,
        offset: int,
    ):
        self.calls.append(
            {
                "owner_identity": owner_identity,
                "limit": limit,
                "offset": offset,
            }
        )

        class Document:
            document_id = "document-1"
            canonical_url = "https://example.com/article"
            title = "Example Article"
            source_type = "web"
            created_at = "2026-11-21T00:00:00Z"
            updated_at = "2026-11-21T00:00:00Z"
            revision_count = 1

        return [Document()], 1


def make_client(repository: FakeDocumentRepository):
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
        "bintu_api.api.routes.rag.SupabaseDocumentRepository",
        return_value=repository,
    ):
        yield TestClient(app)


def test_lists_only_authenticated_user_documents():
    repository = FakeDocumentRepository()

    for client in make_client(repository):
        with patch(
            "bintu_api.api.routes.rag.verify_supabase_user",
            return_value="user-1",
        ):
            response = client.get(
                "/api/v1/mobile/rag/documents?limit=20&offset=0",
                headers={"Authorization": "Bearer valid-session"},
            )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["total"] == 1
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert len(body["documents"]) == 1
    assert body["documents"][0]["document_id"] == "document-1"
    assert body["documents"][0]["revision_count"] == 1

    assert repository.calls == [
        {
            "owner_identity": "user-1",
            "limit": 20,
            "offset": 0,
        }
    ]


def test_rejects_invalid_limit():
    repository = FakeDocumentRepository()

    for client in make_client(repository):
        with patch(
            "bintu_api.api.routes.rag.verify_supabase_user",
            return_value="user-1",
        ):
            response = client.get(
                "/api/v1/mobile/rag/documents?limit=0",
                headers={"Authorization": "Bearer valid-session"},
            )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_limit"
