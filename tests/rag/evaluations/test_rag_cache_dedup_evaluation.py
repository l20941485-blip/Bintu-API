"""Evaluation tests for unchanged SHA-256 re-ingestion, cache bypass, and statement deduplication."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from bintu_api.extraction.rag_chunking import SemanticChunk
from bintu_api.rag.answer import RagAnswerService
from bintu_api.rag.ingestion import RagIngestionService
from bintu_api.rag.ingestion_workflow import ingest_url_to_knowledge_core
from bintu_api.rag.models import Document, DocumentRevision, IngestedRevision, RagChunk
from bintu_api.rag.retrieval import RagRetrievalService, RetrievedChunk


class _FakeRateLimiter:
    def check(self, _identity: str) -> None:
        return None


class _FakeChunkRepository:
    def __init__(self) -> None:
        self.calls: list[tuple[Document, DocumentRevision, list[RagChunk]]] = []
        self._last_revision_by_doc: dict[str, DocumentRevision] = {}

    async def ingest_revision(
        self,
        document: Document,
        revision: DocumentRevision,
        chunks: list[RagChunk],
    ) -> IngestedRevision:
        self.calls.append((document, revision, chunks))
        previous = self._last_revision_by_doc.get(document.document_id)
        unchanged = previous is not None and previous.content_sha256 == revision.content_sha256
        revision_id = (
            previous.revision_id
            if unchanged and previous and previous.revision_id
            else f"rev-{len(self.calls)}"
        )
        stored = DocumentRevision(
            revision_id=revision_id,
            document_id=document.document_id,
            source_url=revision.source_url,
            final_url=revision.final_url,
            content_sha256=revision.content_sha256,
            content_fingerprint=revision.content_fingerprint,
            extracted_at=revision.extracted_at,
            language=revision.language,
            status=revision.status,
        )
        self._last_revision_by_doc[document.document_id] = stored
        return IngestedRevision(
            revision_id=revision_id,
            document=document,
            revision=stored,
            chunks=tuple(chunks),
        )


class _OverlappingChunkRepository:
    def __init__(self, chunks: list[RetrievedChunk]) -> None:
        self._chunks = chunks

    async def search_chunks(
        self,
        *,
        query: str,
        limit: int,
        access_labels: tuple[str, ...],
        owner_identity: str | None,
        document_id: str | None = None,
    ) -> list[RetrievedChunk]:
        return self._chunks[:limit]


class RagCacheAndDedupEvaluationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.request = SimpleNamespace(
            app=SimpleNamespace(
                state=SimpleNamespace(
                    supabase_client=object(),
                    rate_limiter=_FakeRateLimiter(),
                )
            ),
            headers={},
            client=SimpleNamespace(host="127.0.0.1"),
        )
        self.settings = SimpleNamespace(
            rapidapi_proxy_secret=None,
            trust_proxy_headers=False,
        )
        self.repo = _FakeChunkRepository()

    def _make_request_with_repo(self) -> SimpleNamespace:
        repo = self.repo

        class BoundRepo:
            def __init__(self, _client: object) -> None:
                self._repo = repo

            async def ingest_revision(
                self,
                document: Document,
                revision: DocumentRevision,
                chunks: list[RagChunk],
            ) -> IngestedRevision:
                return await self._repo.ingest_revision(document, revision, chunks)

        self.request.app.state.bound_repo_cls = BoundRepo
        return self.request

    def _semantic_chunks(self, body: str) -> list[SemanticChunk]:
        token_count = max(1, len(body) // 4)
        return [
            SemanticChunk(
                chunk_id="chunk-0",
                index=0,
                chunk_strategy="semantic",
                text=body,
                heading_path=("Docs",),
                approx_tokens=token_count,
                tokens=token_count,
            )
        ]

    async def test_unchanged_content_sha256_reuses_revision_identity(self) -> None:
        self._make_request_with_repo()
        seen_skip_cache: list[bool] = []

        async def fake_extract(_req, _url, *, skip_cache: bool, **_kwargs):
            seen_skip_cache.append(skip_cache)
            doc = SimpleNamespace(final_url="https://example.com/guide")
            result = SimpleNamespace(
                markdown="# Guide\n\nRotate API keys every 90 days.",
                page_title="Guide",
                content_hash="sha256:same-hash",
                content_fingerprint="fp-1",
                extracted_at="2026-11-26T00:00:00Z",
            )
            return doc, result, "memory", False

        first = await ingest_url_to_knowledge_core(
            self.request,
            self.settings,
            "https://example.com/guide",
            owner_identity="user-1",
            skip_cache=False,
            extract_fn=fake_extract,
            chunk_fn=lambda text, **_kw: self._semantic_chunks(text),
            chunk_repository_cls=self.request.app.state.bound_repo_cls,
            ingestion_service_cls=RagIngestionService,
        )
        second = await ingest_url_to_knowledge_core(
            self.request,
            self.settings,
            "https://example.com/guide",
            owner_identity="user-1",
            skip_cache=False,
            extract_fn=fake_extract,
            chunk_fn=lambda text, **_kw: self._semantic_chunks(text),
            chunk_repository_cls=self.request.app.state.bound_repo_cls,
            ingestion_service_cls=RagIngestionService,
        )

        self.assertEqual(seen_skip_cache, [False, False])
        self.assertEqual(first.revision.revision_id, second.revision.revision_id)
        self.assertEqual(first.revision.content_sha256, "sha256:same-hash")
        self.assertEqual(second.revision.content_sha256, "sha256:same-hash")
        self.assertEqual(len(self.repo.calls), 2)

    async def test_skip_cache_bypasses_stale_extraction_result(self) -> None:
        self._make_request_with_repo()
        seen_skip_cache: list[bool] = []

        async def fake_extract(_req, _url, *, skip_cache: bool, **_kwargs):
            seen_skip_cache.append(skip_cache)
            doc = SimpleNamespace(final_url="https://example.com/limits")
            if not skip_cache:
                result = SimpleNamespace(
                    markdown="# Limits\n\nRate limit is 100 requests per minute.",
                    page_title="Limits",
                    content_hash="sha256:stale",
                    content_fingerprint="fp-stale",
                    extracted_at="2026-11-26T00:00:00Z",
                )
            else:
                result = SimpleNamespace(
                    markdown="# Limits\n\nRate limit is 500 requests per minute.",
                    page_title="Limits",
                    content_hash="sha256:fresh",
                    content_fingerprint="fp-fresh",
                    extracted_at="2026-11-26T00:01:00Z",
                )
            return doc, result, "memory" if not skip_cache else "none", skip_cache

        cached = await ingest_url_to_knowledge_core(
            self.request,
            self.settings,
            "https://example.com/limits",
            owner_identity="user-1",
            skip_cache=False,
            extract_fn=fake_extract,
            chunk_fn=lambda text, **_kw: self._semantic_chunks(text),
            chunk_repository_cls=self.request.app.state.bound_repo_cls,
            ingestion_service_cls=RagIngestionService,
        )
        bypassed = await ingest_url_to_knowledge_core(
            self.request,
            self.settings,
            "https://example.com/limits",
            owner_identity="user-1",
            skip_cache=True,
            extract_fn=fake_extract,
            chunk_fn=lambda text, **_kw: self._semantic_chunks(text),
            chunk_repository_cls=self.request.app.state.bound_repo_cls,
            ingestion_service_cls=RagIngestionService,
        )

        self.assertEqual(seen_skip_cache, [False, True])
        self.assertEqual(cached.revision.content_sha256, "sha256:stale")
        self.assertEqual(bypassed.revision.content_sha256, "sha256:fresh")
        self.assertNotEqual(cached.revision.revision_id, bypassed.revision.revision_id)

    async def test_overlapping_chunks_deduplicate_repeated_statements(self) -> None:
        overlapping_chunks = [
            RetrievedChunk(
                chunk_id="chunk-overlap-1",
                revision_id="rev-1",
                document_id="doc-1",
                text="## Auth\n\nUse an API key for every request.\n\nKeep keys in environment variables.",
                score=0.95,
                source_url="https://example.com/auth",
                final_url="https://example.com/auth",
                heading_path=("Auth",),
                access_labels=("public",),
            ),
            RetrievedChunk(
                chunk_id="chunk-overlap-2",
                revision_id="rev-1",
                document_id="doc-1",
                text="Keep keys in environment variables.\n\nUse an API key for every request.",
                score=0.90,
                source_url="https://example.com/auth",
                final_url="https://example.com/auth",
                heading_path=("Auth", "Security"),
                access_labels=("public",),
            ),
        ]
        retrieval = RagRetrievalService(_OverlappingChunkRepository(overlapping_chunks))
        answer_service = RagAnswerService(retrieval)

        result = await answer_service.answer(
            query="How do I use an API key?",
            limit=5,
            access_labels=("public",),
            owner_identity=None,
        )

        occurrences = result.answer.count("Use an API key for every request.")
        self.assertEqual(occurrences, 1)
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0].chunk_id, "chunk-overlap-1")
