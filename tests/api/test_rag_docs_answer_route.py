"""Contract tests for the public Bintu documentation answer endpoint."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from bintu_api.api.routes import rag as rag_routes
from bintu_api.rag.retrieval import RetrievedChunk


class FakeDocsRetrievalRepository:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks
        self.calls: list[dict[str, object]] = []

    async def search_chunks(
        self,
        *,
        query: str,
        limit: int,
        access_labels: tuple[str, ...],
        owner_identity: str | None,
        document_id: str | None = None,
    ) -> list[RetrievedChunk]:
        self.calls.append(
            {
                "query": query,
                "limit": limit,
                "access_labels": access_labels,
                "owner_identity": owner_identity,
            }
        )
        return self._chunks[:limit]


def make_chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id="chunk-docs-auth",
        revision_id="revision-1",
        document_id="document-docs",
        text="## Authentication\n\nUse an API key.",
        score=1.0,
        source_url="https://docs.example.com/authentication",
        final_url="https://docs.example.com/authentication",
        heading_path=("Documentation", "Authentication"),
        access_labels=("docs",),
    )


class RagDocsAnswerRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.repository = FakeDocsRetrievalRepository([make_chunk()])
        self.app = FastAPI()
        self.app.include_router(rag_routes.router)
        self.app.state.settings = Mock()
        self.app.state.rate_limiter = Mock()
        self.app.state.supabase_client = Mock()
        self.client = TestClient(self.app)

    def test_docs_answer_is_restricted_to_docs_collection(self) -> None:
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
                "SupabaseRetrievalRepository",
                return_value=self.repository,
            ),
        ):
            response = self.client.post(
                "/api/v1/rag/docs/answers",
                json={
                    "query": "How do I authenticate?",
                    "limit": 5,
                },
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()

        self.assertFalse(body["insufficient_evidence"])
        self.assertEqual(body["answer"], "Use an API key.")
        self.assertEqual(len(body["citations"]), 1)
        self.assertEqual(
            body["citations"][0]["chunk_id"],
            "chunk-docs-auth",
        )
        self.assertEqual(
            body["citations"][0]["source_url"],
            "https://docs.example.com/authentication",
        )

        self.assertEqual(len(self.repository.calls), 1)
        self.assertEqual(
            self.repository.calls[0]["access_labels"],
            ("docs",),
        )
        self.assertIsNone(self.repository.calls[0]["owner_identity"])

    def test_docs_answer_rejects_blank_query(self) -> None:
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
                "SupabaseRetrievalRepository",
                return_value=self.repository,
            ),
        ):
            response = self.client.post(
                "/api/v1/rag/docs/answers",
                json={"query": "   "},
            )

        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
