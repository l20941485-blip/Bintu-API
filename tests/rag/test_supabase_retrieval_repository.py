"""Tests for the Supabase-backed RAG retrieval repository."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock

from bintu_api.rag.supabase_retrieval import SupabaseRetrievalRepository


class SupabaseRetrievalRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_calls_keyword_retrieval_rpc(self) -> None:
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

        repository = SupabaseRetrievalRepository(supabase)
        results = await repository.search_chunks(
            query="authentication",
            limit=5,
            access_labels=("public",),
            owner_identity=None,
            document_id="document-1",
        )

        supabase.rpc.assert_called_once_with(
            "search_rag_chunks",
            {
                "p_query": "authentication",
                "p_limit": 5,
                "p_access_labels": ["public"],
                "p_owner_identity": None,
                "p_document_id": "document-1",
            },
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].chunk_id, "chunk-auth")
        self.assertEqual(results[0].revision_id, "revision-1")
        self.assertEqual(results[0].document_id, "document-1")
        self.assertEqual(results[0].score, 1.0)
        self.assertEqual(
            results[0].heading_path,
            ("Guide", "Authentication"),
        )
        self.assertEqual(results[0].access_labels, ("public",))


if __name__ == "__main__":
    unittest.main(verbosity=2)
