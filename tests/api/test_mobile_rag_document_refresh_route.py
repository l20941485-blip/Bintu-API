"""Contract tests for refreshing a mobile user's RAG document."""

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


class FakeIngestion:
    def __init__(self) -> None:
        self.requests = []

    async def ingest(self, request):
        self.requests.append(request)

        class Chunk:
            chunk_id = "chunk-refreshed"
            chunk_index = 0
            chunk_sha256 = "a" * 64

        class Document:
            document_id = "document-1"

        class Result:
            document = Document()
            revision_id = "revision-2"
            chunks = [Chunk()]

        return Result()


class FakeExtractionResult:
    markdown = "# Updated Guide\n\nUpdated introduction."
    content_hash = "sha256:updated-content"
    content_fingerprint = "sha256:updated-fingerprint"
    extracted_at = "2026-11-21T01:00:00+00:00"
    page_title = "Updated Documentation"


class FakeDocument:
    final_url = "https://example.com/article"


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
        "chunks": [],
    }


def make_client(detail_repository: FakeDetailRepository, ingestion: FakeIngestion):
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

    with (
        patch(
            "bintu_api.api.routes.rag.SupabaseDocumentDetailRepository",
            return_value=detail_repository,
        ),
        patch(
            "bintu_api.api.routes.rag.SupabaseChunkRepository",
            return_value=Mock(),
        ),
        patch(
            "bintu_api.api.routes.rag.RagIngestionService",
            return_value=ingestion,
        ),
    ):
        yield TestClient(app)


def test_refreshes_owned_document():
    details = make_details()
    detail_repository = FakeDetailRepository(details)
    ingestion = FakeIngestion()

    for client in make_client(detail_repository, ingestion):
        with (
            patch(
                "bintu_api.api.routes.rag.verify_supabase_user",
                return_value="user-1",
            ),
            patch(
                "bintu_api.api.routes.rag.fetch_and_extract",
                new=AsyncMock(
                    return_value=(
                        FakeDocument(),
                        FakeExtractionResult(),
                        None,
                        False,
                    )
                ),
            ),
            patch(
                "bintu_api.api.routes.rag.split_semantic_chunks",
                return_value=[
                    Mock(
                        chunk_id="chunk-refreshed",
                        chunk_index=0,
                        chunk_sha256="a" * 64,
                    )
                ],
            ),
        ):
            response = client.post(
                "/api/v1/mobile/rag/documents/document-1/refresh",
                json={
                    "max_tokens": 1000,
                    "overlap_tokens": 0,
                    "access_labels": [],
                },
                headers={"Authorization": "Bearer valid-session"},
            )

    assert response.status_code == 200, response.text
    body = response.json()

    assert body["document_id"] == "document-1"
    assert body["revision_id"] == "revision-2"
    assert body["chunk_count"] == 1
    assert body["chunks"][0]["chunk_id"] == "chunk-refreshed"

    assert detail_repository.calls == [
        {
            "owner_identity": "user-1",
            "document_id": "document-1",
        }
    ]

    assert len(ingestion.requests) == 1
    request = ingestion.requests[0]

    assert request.owner_identity == "user-1"
    assert request.canonical_url == "https://example.com/article"
    assert request.access_labels == ()


def test_returns_404_for_document_not_owned_by_user():
    detail_repository = FakeDetailRepository(None)
    ingestion = FakeIngestion()

    for client in make_client(detail_repository, ingestion):
        with patch(
            "bintu_api.api.routes.rag.verify_supabase_user",
            return_value="user-1",
        ):
            response = client.post(
                "/api/v1/mobile/rag/documents/document-other/refresh",
                json={},
                headers={"Authorization": "Bearer valid-session"},
            )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "document_not_found"
    assert ingestion.requests == []
