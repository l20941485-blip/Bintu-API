-- Enforce strict separation between user-owned RAG documents and shared 'docs' documents.

begin;

alter table public.rag_documents
    drop constraint if exists rag_documents_owner_identity_non_empty_chk;

alter table public.rag_documents
    add constraint rag_documents_owner_identity_non_empty_chk
    check (owner_identity is null or btrim(owner_identity) <> '');

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
    v_canonical_url text;
    v_source_type text;
    v_chunk_count integer;
    v_all_chunks_are_docs boolean;
begin
    v_owner_identity := nullif(btrim(p_document->>'owner_identity'), '');
    v_canonical_url := nullif(btrim(p_document->>'canonical_url'), '');
    v_source_type := coalesce(nullif(btrim(p_document->>'source_type'), ''), 'web');

    if v_canonical_url is null then
        raise exception 'canonical_url is required for knowledge ingestion';
    end if;

    select
        count(*)::integer,
        coalesce(
            bool_and(
                exists (
                    select 1
                    from jsonb_array_elements_text(coalesce(elem->'access_labels', '[]'::jsonb)) as lbl
                    where lbl = 'docs'
                )
            ),
            false
        )
    into v_chunk_count, v_all_chunks_are_docs
    from jsonb_array_elements(coalesce(p_chunks, '[]'::jsonb)) as elem;

    if v_owner_identity is null then
        if v_chunk_count = 0 or not v_all_chunks_are_docs then
            raise exception 'owner_identity is required for user-owned knowledge ingestion';
        end if;
    end if;

    select *
    into v_document
    from public.rag_documents
    where coalesce(owner_identity, '') = coalesce(v_owner_identity, '')
      and canonical_url = v_canonical_url
      and source_type = v_source_type
    for update;

    if not found then
        insert into public.rag_documents (
            canonical_url,
            source_type,
            title,
            owner_identity
        )
        values (
            v_canonical_url,
            v_source_type,
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
