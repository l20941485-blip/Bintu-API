# RAG knowledge core

## Purpose

The RAG knowledge core stores canonical extracted web content as retrieval-ready chunks with stable identity, provenance, and access metadata.

## Data model

- `Document`: canonical source identity.
- `DocumentRevision`: immutable extracted-content version.
- `Chunk`: retrieval-ready unit derived from one revision.

## Identity

- Documents are identified by normalized canonical URL and source type.
- Revisions are identified by document, content hash, and extraction configuration.
- Chunks reuse the existing deterministic chunk ID scheme.
- `chunk_sha256` identifies exact chunk text.
- `content_sha256` identifies canonical revision content.

## Access model

The initial system is service-owned. `owner_identity` is optional and supports future per-user or workspace knowledge bases. `access_labels` provide retrieval-time authorization metadata.

## Storage

Postgres is the canonical store for documents, revisions, chunks, metadata, and retrieval indexes. Chunk text remains in Postgres for the initial implementation.

## Retrieval roadmap

1. Keyword retrieval baseline.
2. Golden evaluation set.
3. pgvector embeddings.
4. Hybrid retrieval with reciprocal rank fusion.
5. Reranking.
6. Grounded answer generation with chunk-level citations.
7. Adaptive multi-hop agent behavior.

## Non-goals

Do not introduce tenant RLS, pgvector, GraphRAG, or autonomous multi-agent orchestration before the retrieval baseline and evaluation harness exist.
