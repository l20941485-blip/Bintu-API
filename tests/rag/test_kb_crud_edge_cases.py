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


def test_list_documents_validates_bounds_and_computes_has_more() -> None:
    captured_params: dict[str, object] = {}

    class _PagedClient:
        def rpc(self, _name, params):
            captured_params.update(params)

            class _Exec:
                async def execute(self):
                    return _rpc_response(
                        [
                            {
                                "document_id": "d-3",
                                "canonical_url": "https://example.com/3",
                                "title": "Doc 3",
                                "source_type": "web",
                                "created_at": "2026-11-27T00:00:00Z",
                                "updated_at": "2026-11-27T00:00:00Z",
                                "revision_count": 1,
                                "total": 5,
                            }
                        ]
                    )

            return _Exec()

    repo = SupabaseDocumentRepository(_PagedClient())
    docs, total = asyncio.run(repo.list_documents(owner_identity="tenant-a", limit=2, offset=2))
    assert captured_params == {
        "p_owner_identity": "tenant-a",
        "p_limit": 2,
        "p_offset": 2,
    }
    assert len(docs) == 1
    assert total == 5
    assert (2 + len(docs)) < total

    with pytest.raises(ValueError, match="limit"):
        asyncio.run(repo.list_documents(owner_identity="tenant-a", limit=0, offset=0))

    with pytest.raises(ValueError, match="offset"):
        asyncio.run(repo.list_documents(owner_identity="tenant-a", limit=5, offset=-1))


def test_rag_answer_observability_records_selected_evidence_count() -> None:
    from bintu_api.rag.answer import RagAnswerService
    from bintu_api.rag.retrieval import RetrievedChunk

    recorded = []

    class _RecordingObserver:
        def record_answer(self, event) -> None:
            recorded.append(event)

    class _StubRetrieval:
        async def search(self, *, query: str, limit: int, access_labels, owner_identity, document_id):
            return [
                RetrievedChunk(
                    chunk_id="c-1",
                    revision_id="r-1",
                    document_id="d-1",
                    source_url="https://example.com/doc",
                    final_url="https://example.com/doc",
                    heading_path=("Guide",),
                    access_labels=(),
                    text="Tenant isolation enforces strict boundaries.\nTenant isolation prevents cross-tenant leaks.",
                    score=0.9,
                )
            ]

    service = RagAnswerService(_StubRetrieval(), observer=_RecordingObserver())
    result = asyncio.run(
        service.answer(
            query="tenant isolation",
            limit=5,
            owner_identity="tenant-1",
        )
    )

    assert not result.insufficient_evidence
    assert len(recorded) == 1
    event = recorded[0]
    assert event.selected_evidence_count == 2
    assert event.citation_count == 1
    assert event.abstention_reason is None
