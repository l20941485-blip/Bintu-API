"""Ensure Supabase ingestion preserves the database-issued document identity."""

from __future__ import annotations

import unittest
import uuid
from typing import Any

from bintu_api.extraction.rag_chunking import split_semantic_chunks
from bintu_api.rag.ingestion import (
    ExtractionIngestionRequest,
    RagIngestionService,
)
from bintu_api.rag.supabase import (
    SupabaseChunkRepository,
    SupabaseDocumentDetailRepository,
)
from bintu_api.rag.supabase_retrieval import SupabaseRetrievalRepository


class _FakeRpc:
    def __init__(self, client: _FakeSupabaseClient, name: str, params: dict[str, Any]) -> None:
        self._client = client
        self._name = name
        self._params = params

    async def execute(self) -> Any:
        self._client.calls.append((self._name, self._params))

        if self._name == "ingest_rag_revision":
            document_id = str(uuid.uuid4())
            revision_id = str(uuid.uuid4())
            chunks = self._params["p_chunks"]
            self._client.ingested_document_id = document_id
            self._client.ingested_revision_id = revision_id

            return type(
                "Response",
                (),
                {
                    "data": {
                        "document_id": document_id,
                        "revision_id": revision_id,
                        "chunks": [
                            {
                                "chunk_id": chunk["chunk_id"],
                                "chunk_sha256": chunk["chunk_sha256"],
                                "chunk_index": chunk["chunk_index"],
                            }
                            for chunk in chunks
                        ],
                    }
                },
            )()

        if self._name == "get_rag_document_details":
            assert self._params["p_document_id"] == self._client.ingested_document_id
            return type(
                "Response",
                (),
                {"data": {"document": {}, "revision": {}, "chunks": []}},
            )()

        if self._name == "search_rag_chunks":
            assert self._params["p_document_id"] == self._client.ingested_document_id
            return type("Response", (), {"data": []})()

        raise AssertionError(f"Unexpected RPC: {self._name}")


class _FakeSupabaseClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.ingested_document_id: str | None = None
        self.ingested_revision_id: str | None = None

    def rpc(self, name: str, params: dict[str, Any]) -> _FakeRpc:
        return _FakeRpc(self, name, params)


class SupabaseIngestionDocumentIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def test_ingestion_uses_database_document_id(self) -> None:
        client = _FakeSupabaseClient()
        markdown = (
            "# Guide\n\nBintu knowledge ingestion.\n\n"
            "## Authentication\n\nUse an API key."
        )
        chunks = split_semantic_chunks(
            markdown,
            max_tokens=200,
            overlap_tokens=0,
            source_url="https://example.com/guide",
            final_url="https://example.com/guide",
            content_sha256="sha256:content",
            extracted_at="2026-11-22T00:00:00+00:00",
        )

        request = ExtractionIngestionRequest(
            canonical_url="https://example.com/guide",
            title="Bintu Guide",
            source_type="web",
            owner_identity="user-1",
            source_url="https://example.com/guide",
            final_url="https://example.com/guide",
            content_sha256="sha256:content",
            content_fingerprint="sha256:content-fingerprint",
            extracted_at="2026-11-22T00:00:00+00:00",
            language="en",
            status="active",
            chunks=chunks,
            access_labels=(),
        )

        repository = SupabaseChunkRepository(client)
        result = await RagIngestionService(repository).ingest(request)

        self.assertIsNotNone(client.ingested_document_id)
        self.assertEqual(result.document.document_id, client.ingested_document_id)
        self.assertEqual(result.revision.document_id, client.ingested_document_id)

        for chunk in result.chunks:
            self.assertEqual(chunk.document_id, client.ingested_document_id)
            self.assertEqual(chunk.revision_id, client.ingested_revision_id)

        detail_repository = SupabaseDocumentDetailRepository(client)
        await detail_repository.get_document_details(
            owner_identity="user-1",
            document_id=result.document.document_id,
        )

        retrieval_repository = SupabaseRetrievalRepository(client)
        await retrieval_repository.search_chunks(
            query="ingestion",
            limit=5,
            access_labels=(),
            owner_identity="user-1",
            document_id=result.document.document_id,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
