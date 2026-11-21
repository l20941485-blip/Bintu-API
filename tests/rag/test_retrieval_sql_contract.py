"""Static contract tests for tenant-aware RAG retrieval SQL."""

from pathlib import Path

MIGRATION = Path(
    "supabase/migrations/20261121153000_rag_tenant_isolation.sql"
).read_text(encoding="utf-8")

SCHEMA = Path("supabase_schema.sql").read_text(encoding="utf-8")


def test_sql_joins_chunks_to_documents_for_ownership() -> None:
    assert "join public.rag_documents document" in MIGRATION
    assert "document.document_id = chunk.document_id" in MIGRATION


def test_sql_allows_public_documents_to_anonymous_callers() -> None:
    assert "document.owner_identity is null" in MIGRATION


def test_sql_allows_owner_documents_to_authenticated_callers() -> None:
    assert "document.owner_identity = p_owner_identity" in MIGRATION


def test_sql_treats_empty_access_labels_as_unfiltered() -> None:
    assert "cardinality(p_access_labels) = 0" in MIGRATION


def test_schema_matches_tenant_isolation_migration() -> None:
    for fragment in (
        "join public.rag_documents document",
        "document.owner_identity is null",
        "document.owner_identity = p_owner_identity",
        "cardinality(p_access_labels) = 0",
    ):
        assert fragment in SCHEMA
