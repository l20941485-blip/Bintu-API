from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from bintu_api.rag.models import Document, DocumentRevision, RagChunk
from bintu_api.rag.supabase import (
    SupabaseChunkRepository,
    SupabaseDocumentDeletionRepository,
    SupabaseDocumentRepository,
)


def _rpc_response(data):
    return SimpleNamespace(data=data)


def test_ingest_revision_handles_partial_chunk_metadata_and_rejects_missing_ids() -> None:
    chunks = [
        RagChunk(
            chunk_id="c-0",
            revision_id=None,
            document_id=None,
            owner_identity="u-1",
            chunk_index=0,
            chunk_strategy="semantic",
            text="First chunk text",
            chunk_sha256="",
            heading_path=("Intro",),
            section_path="Intro",
            char_start=0,
            char_end=16,
            source_url="https://example.com/doc",
            final_url="https://example.com/doc",
            content_sha256="sha-doc",
            content_fingerprint="fp-doc",
            extracted_at="2026-11-27T00:00:00Z",
            access_labels=(),
        ),
        RagChunk(
            chunk_id="c-1",
            revision_id=None,
            document_id=None,
            owner_identity="u-1",
            chunk_index=1,
            chunk_strategy="semantic",
            text="Second chunk text",
            chunk_sha256="",
            heading_path=(),
            section_path=None,
            char_start=17,
            char_end=34,
            source_url="https://example.com/doc",
            final_url="https://example.com/doc",
            content_sha256="sha-doc",
            content_fingerprint="fp-doc",
            extracted_at="2026-11-27T00:00:00Z",
            access_labels=(),
        ),
    ]
    doc = Document(
        document_id="doc-1",
        canonical_url="https://example.com/doc",
        title="Doc",
        source_type="web",
        owner_identity="u-1",
    )
    rev = DocumentRevision(
        revision_id=None,
        document_id="doc-1",
        source_url="https://example.com/doc",
        final_url="https://example.com/doc",
        content_sha256="sha-doc",
        content_fingerprint="fp-doc",
        extracted_at="2026-11-27T00:00:00Z",
        language=None,
        status="active",
    )

    class _PartialClient:
        def rpc(self, _name, _params):
            class _Exec:
                async def execute(self):
                    return _rpc_response(
                        {
                            "document_id": "doc-persisted",
                            "revision_id": "rev-persisted",
                            "chunks": [{"chunk_id": "override-0", "chunk_sha256": "override-sha"}],
                        }
                    )

            return _Exec()

    repo = SupabaseChunkRepository(_PartialClient())
    persisted = asyncio.run(repo.ingest_revision(doc, rev, chunks))
    assert persisted.document.document_id == "doc-persisted"
    assert persisted.revision_id == "rev-persisted"
    assert len(persisted.chunks) == 2
    assert persisted.chunks[0].chunk_id == "override-0"
    assert persisted.chunks[0].chunk_sha256 == "override-sha"
    assert persisted.chunks[1].chunk_id == "c-1"
    assert bool(persisted.chunks[1].chunk_sha256)

    class _BadClient:
        def rpc(self, _name, _params):
            class _Exec:
                async def execute(self):
                    return _rpc_response({"document_id": "only-doc"})

            return _Exec()

    with pytest.raises(ValueError, match="revision_id"):
        asyncio.run(SupabaseChunkRepository(_BadClient()).ingest_revision(doc, rev, chunks))


def test_list_documents_fallback_total_and_delete_dict_payload() -> None:
    class _ListClient:
        def rpc(self, _name, _params):
            class _Exec:
                async def execute(self):
                    return _rpc_response(
                        [
                            {
                                "document_id": "d-1",
                                "canonical_url": "https://example.com",
                                "title": "Title",
                                "source_type": "web",
                                "created_at": "2026-11-27T00:00:00Z",
                                "updated_at": "2026-11-27T00:00:00Z",
                                "revision_count": 1,
                            }
                        ]
                    )

            return _Exec()

    docs, total = asyncio.run(SupabaseDocumentRepository(_ListClient()).list_documents(owner_identity="u-1"))
    assert len(docs) == 1
    assert total == 1

    class _FalseDictDeleteClient:
        def rpc(self, _name, _params):
            class _Exec:
                async def execute(self):
                    return _rpc_response({"deleted": False})

            return _Exec()

    assert asyncio.run(
        SupabaseDocumentDeletionRepository(_FalseDictDeleteClient()).delete_document(
            owner_identity="u-1",
            document_id="d-1",
        )
    ) is False
