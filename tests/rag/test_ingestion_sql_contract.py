"""Static contract tests for owner-scoped RAG ingestion SQL."""

from pathlib import Path

MIGRATION = Path(
    "supabase/migrations/20261122110000_rag_owner_scoped_documents.sql"
).read_text(encoding="utf-8")


def test_sql_requires_owner_identity_for_user_ingestion() -> None:
    assert "v_owner_identity := p_document->>'owner_identity'" in MIGRATION
    assert "if v_owner_identity is null or v_owner_identity = '' then" in MIGRATION
    assert (
        "raise exception 'owner_identity is required for user-owned knowledge ingestion'"
        in MIGRATION
    )


def test_sql_scopes_document_identity_to_owner() -> None:
    assert (
        "where owner_identity = v_owner_identity\n"
        "      and canonical_url = p_document->>'canonical_url'\n"
        "      and source_type = coalesce(p_document->>'source_type', 'web')"
        in MIGRATION
    )


def test_sql_does_not_transfer_document_ownership() -> None:
    assert "owner_identity = coalesce(excluded.owner_identity" not in MIGRATION
    assert "on conflict (canonical_url, source_type)" not in MIGRATION


def test_sql_creates_owner_aware_document_uniqueness() -> None:
    assert "drop constraint if exists rag_documents_canonical_url_source_type_key" in MIGRATION
    assert "create unique index if not exists rag_documents_owner_canonical_source_idx" in MIGRATION
    assert "coalesce(owner_identity, '')" in MIGRATION


def test_sql_scopes_chunk_identity_to_document() -> None:
    assert "drop constraint if exists rag_chunks_pkey" in MIGRATION
    assert "primary key (document_id, chunk_id)" in MIGRATION
    assert "on conflict (document_id, chunk_id)" in MIGRATION


def test_sql_limits_ingestion_execution_to_service_role() -> None:
    assert (
        "revoke execute on function public.ingest_rag_revision(jsonb, jsonb, jsonb)\n"
        "    from anon, authenticated;"
        in MIGRATION
    )
    assert (
        "grant execute on function public.ingest_rag_revision(jsonb, jsonb, jsonb)\n"
        "    to service_role;"
        in MIGRATION
    )
