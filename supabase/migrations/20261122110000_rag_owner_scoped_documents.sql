-- Prevent cross-tenant RAG document ownership takeover.
--
-- Documents are scoped to an owner identity. A user may maintain one document
-- per canonical URL and source type, but must never take ownership of another
-- user's document. Chunk identity is also scoped to its document so identical
-- content ingested by different owners cannot overwrite another owner's chunks.

begin;

alter table public.rag_documents
    drop constraint if exists rag_documents_canonical_url_source_type_key;

create unique index if not exists rag_documents_owner_canonical_source_idx
    on public.rag_documents (
        coalesce(owner_identity, ''),
        canonical_url,
        source_type
    );

alter table public.rag_chunks
    drop constraint if exists rag_chunks_pkey;

alter table public.rag_chunks
    add constraint rag_chunks_document_chunk_pkey
    primary key (document_id, chunk_id);

create or replace function public.ingest_rag_revision(
    p_document jsonb,
    p_revision jsonb,
    p_chunks jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_document public.rag_documents;
    v_revision public.rag_document_revisions;
    v_chunk jsonb;
    v_chunk_id text;
    v_chunk_sha256 text;
    v_owner_identity text;
begin
    v_owner_identity := p_document->>'owner_identity';

    if v_owner_identity is null or v_owner_identity = '' then
        raise exception 'owner_identity is required for user-owned knowledge ingestion';
    end if;

    select *
    into v_document
    from public.rag_documents
    where owner_identity = v_owner_identity
      and canonical_url = p_document->>'canonical_url'
      and source_type = coalesce(p_document->>'source_type', 'web')
    for update;

    if not found then
        insert into public.rag_documents (
            canonical_url,
            source_type,
            title,
            owner_identity
        )
        values (
            p_document->>'canonical_url',
            coalesce(p_document->>'source_type', 'web'),
            p_document->>'title',
            v_owner_identity
        )
        returning * into v_document;
    else
        update public.rag_documents
        set title = coalesce(p_document->>'title', public.rag_documents.title),
            updated_at = pg_catalog.now()
        where document_id = v_document.document_id
        returning * into v_document;
    end if;

    insert into public.rag_document_revisions (
        document_id,
        source_url,
        final_url,
        content_sha256,
        content_fingerprint,
        extracted_at,
        language,
        status
    )
    values (
        v_document.document_id,
        p_revision->>'source_url',
        p_revision->>'final_url',
        p_revision->>'content_sha256',
        p_revision->>'content_fingerprint',
        (p_revision->>'extracted_at')::timestamptz,
        p_revision->>'language',
        coalesce(p_revision->>'status', 'active')
    )
    on conflict (document_id, content_sha256) do update
    set final_url = excluded.final_url,
        content_fingerprint = excluded.content_fingerprint,
        extracted_at = excluded.extracted_at,
        language = excluded.language,
        status = excluded.status
    returning * into v_revision;

    delete from public.rag_chunks
    where revision_id = v_revision.revision_id;

    for v_chunk in select * from jsonb_array_elements(p_chunks)
    loop
        v_chunk_id := v_chunk->>'chunk_id';
        v_chunk_sha256 := v_chunk->>'chunk_sha256';

        insert into public.rag_chunks (
            chunk_id,
            revision_id,
            document_id,
            owner_identity,
            chunk_index,
            chunk_strategy,
            text,
            chunk_sha256,
            heading_path,
            section_path,
            char_start,
            char_end,
            source_url,
            final_url,
            content_sha256,
            content_fingerprint,
            extracted_at,
            access_labels
        )
        values (
            v_chunk_id,
            v_revision.revision_id,
            v_document.document_id,
            v_document.owner_identity,
            (v_chunk->>'chunk_index')::integer,
            v_chunk->>'chunk_strategy',
            v_chunk->>'text',
            v_chunk_sha256,
            (
                select coalesce(array_agg(value::text), '{}')
                from jsonb_array_elements_text(v_chunk->'heading_path') as value
            ),
            v_chunk->>'section_path',
            (v_chunk->>'char_start')::integer,
            (v_chunk->>'char_end')::integer,
            v_chunk->>'source_url',
            v_chunk->>'final_url',
            v_chunk->>'content_sha256',
            v_chunk->>'content_fingerprint',
            (v_chunk->>'extracted_at')::timestamptz,
            (
                select coalesce(array_agg(value::text), '{}')
                from jsonb_array_elements_text(v_chunk->'access_labels') as value
            )
        )
        on conflict (document_id, chunk_id) do update
        set revision_id = excluded.revision_id,
            owner_identity = excluded.owner_identity,
            chunk_index = excluded.chunk_index,
            chunk_strategy = excluded.chunk_strategy,
            text = excluded.text,
            chunk_sha256 = excluded.chunk_sha256,
            heading_path = excluded.heading_path,
            section_path = excluded.section_path,
            char_start = excluded.char_start,
            char_end = excluded.char_end,
            source_url = excluded.source_url,
            final_url = excluded.final_url,
            content_sha256 = excluded.content_sha256,
            content_fingerprint = excluded.content_fingerprint,
            extracted_at = excluded.extracted_at,
            access_labels = excluded.access_labels;
    end loop;

    return jsonb_build_object(
        'document_id', v_document.document_id,
        'revision_id', v_revision.revision_id,
        'chunks', (
            select coalesce(jsonb_agg(jsonb_build_object(
                'chunk_id', chunk_id,
                'chunk_sha256', chunk_sha256,
                'chunk_index', chunk_index
            ) order by chunk_index), '[]'::jsonb)
            from public.rag_chunks
            where revision_id = v_revision.revision_id
        )
    );
end;
$$;

revoke execute on function public.ingest_rag_revision(jsonb, jsonb, jsonb)
    from anon, authenticated;

grant execute on function public.ingest_rag_revision(jsonb, jsonb, jsonb)
    to service_role;

commit;
