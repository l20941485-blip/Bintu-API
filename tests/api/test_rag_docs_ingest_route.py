"""Contract tests for the Bintu documentation ingestion endpoint."""

from __future__ import annotations

import unittest
from typing import ClassVar
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bintu_api.api.routes import rag as rag_routes


class FakeIngestion:
    def __init__(self) -> None:
        self.requests = []

    async def ingest(self, request):
        self.requests.append(request)

        class Chunk:
            chunk_id = "chunk-docs-1"
            chunk_index = 0
            chunk_sha256 = "a" * 64

        class Revision:
            revision_id = "revision-1"

        class Document:
            document_id = "document-docs"

        class Result:
            document = Document()
            revision_id = "revision-1"
            chunks: ClassVar[list[Chunk]] = [Chunk()]

        return Result()


class FakeExtractionResult:
    markdown = "# Authentication\n\nUse an API key."
    content_hash = "b" * 64
    content_fingerprint = "c" * 64
    extracted_at = "2026-01-01T00:00:00Z"
    page_title = "Authentication"


class FakeDocument:
    final_url = "https://docs.example.com/authentication"


class RagDocsIngestRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ingestion = FakeIngestion()
        self.app = FastAPI()
        self.app.include_router(rag_routes.router)
        self.app.state.settings = Mock()
        self.app.state.settings.api_key = "docs-ingest-test-key"
        self.app.state.settings.rapidapi_proxy_secret = ""
        self.app.state.settings.require_auth = True
        self.app.state.settings.rag_jwt_secret = "docs-ingest-test-jwt-secret"
        self.app.state.settings.rag_api_key_owners_json = ""
        self.app.state.settings.rag_default_owner = ""
        self.app.state.rate_limiter = Mock()
        self.app.state.supabase_client = Mock()
        self.client = TestClient(self.app)

    def test_ingests_documentation_into_docs_collection(self) -> None:
        with (
            patch.object(
                rag_routes.routes_common,
                "verify_api_access",
                return_value=None,
            ),
            patch.object(
                rag_routes.routes_common,
                "rate_limit_identity",
                return_value="caller-1",
            ),
            patch.object(
                rag_routes,
                "fetch_and_extract",
                new=AsyncMock(
                    return_value=(
                        FakeDocument(),
                        FakeExtractionResult(),
                        None,
                        False,
                    )
                ),
            ),
            patch.object(
                rag_routes,
                "split_semantic_chunks",
                return_value=[
                    Mock(
                        chunk_id="chunk-docs-1",
                        chunk_index=0,
                        chunk_sha256="a" * 64,
                    )
                ],
            ),
            patch.object(
                rag_routes,
                "SupabaseChunkRepository",
                return_value=Mock(),
            ),
            patch.object(
                rag_routes,
                "RagIngestionService",
                return_value=self.ingestion,
            ),
        ):
            response = self.client.post(
                "/api/v1/rag/docs/ingest",
                headers={"X-API-Key": "docs-ingest-test-key"},
                json={
                    "url": "https://docs.example.com/authentication",
                    "max_tokens": 1000,
                    "overlap_tokens": 0,
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertEqual(body["document_id"], "document-docs")
        self.assertEqual(body["revision_id"], "revision-1")
        self.assertEqual(body["chunk_count"], 1)
        self.assertEqual(
            body["chunks"][0]["chunk_id"],
            "chunk-docs-1",
        )

        self.assertEqual(len(self.ingestion.requests), 1)
        request = self.ingestion.requests[0]

        self.assertIsNone(request.owner_identity)
        self.assertEqual(request.access_labels, ("docs",))
        self.assertEqual(
            request.source_url,
            "https://docs.example.com/authentication",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
