"""Contract tests for deleting a mobile user's RAG document."""

from __future__ import annotations

from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bintu_api.api.routes.rag import router
from bintu_api.security.rate_limit import BurstRateLimiter
from bintu_api.settings import Settings


class FakeDeletionRepository:
    def __init__(self, deleted: bool) -> None:
        self.deleted = deleted
        self.calls = []

    async def delete_document(
        self,
        *,
        owner_identity: str,
        document_id: str,
    ) -> bool:
        self.calls.append(
            {
                "owner_identity": owner_identity,
                "document_id": document_id,
            }
        )
        return self.deleted


def make_client(repository: FakeDeletionRepository):
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
        "bintu_api.api.routes.rag.SupabaseDocumentDeletionRepository",
        return_value=repository,
    ):
        yield TestClient(app)


def test_deletes_authenticated_user_document():
    repository = FakeDeletionRepository(deleted=True)

    for client in make_client(repository):
        with patch(
            "bintu_api.api.routes.rag.verify_supabase_user",
            return_value="user-1",
        ):
            response = client.delete(
                "/api/v1/mobile/rag/documents/document-1",
                headers={"Authorization": "Bearer valid-session"},
            )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body == {
        "document_id": "document-1",
        "deleted": True,
    }
    assert repository.calls == [
        {
            "owner_identity": "user-1",
            "document_id": "document-1",
        }
    ]


def test_returns_404_for_document_not_owned_by_user():
    repository = FakeDeletionRepository(deleted=False)

    for client in make_client(repository):
        with patch(
            "bintu_api.api.routes.rag.verify_supabase_user",
            return_value="user-1",
        ):
            response = client.delete(
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
