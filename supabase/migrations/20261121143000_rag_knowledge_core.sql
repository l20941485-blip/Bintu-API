-- RAG knowledge core: canonical documents, immutable revisions, and retrieval-ready chunks.

create table if not exists public.rag_documents (
    document_id uuid primary key default gen_random_uuid(),
    canonical_url text not null,
    source_type text not null default 'web',
    title text,
    owner_identity text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (canonical_url, source_type)
);

create table if not exists public.rag_document_revisions (
    revision_id uuid primary key default gen_random_uuid(),
    document_id uuid not null references public.rag_documents(document_id) on delete cascade,
    source_url text not null,
    final_url text,
    content_sha256 text not null,
    content_fingerprint text,
    extracted_at timestamptz not null,
    language text,
    status text not null default 'active',
    created_at timestamptz not null default now(),
    unique (document_id, content_sha256)
);

create table if not exists public.rag_chunks (
    chunk_id text primary key,
    revision_id uuid not null references public.rag_document_revisions(revision_id) on delete cascade,
    document_id uuid not null references public.rag_documents(document_id) on delete cascade,
    owner_identity text,
    chunk_index integer not null,
    chunk_strategy text not null,
    text text not null,
    chunk_sha256 text not null,
    heading_path text[] not null default '{}',
    section_path text,
    char_start integer,
    char_end integer,
    source_url text not null,
    final_url text,
    content_sha256 text not null,
    content_fingerprint text,
    extracted_at timestamptz not null,
    access_labels text[] not null default '{}',
    created_at timestamptz not null default now()
);

create index if not exists rag_chunks_revision_id_idx
    on public.rag_chunks (revision_id, chunk_index);

create index if not exists rag_chunks_document_id_idx
    on public.rag_chunks (document_id);

create index if not exists rag_chunks_access_labels_idx
    on public.rag_chunks using gin (access_labels);

alter table public.rag_documents enable row level security;
alter table public.rag_document_revisions enable row level security;
alter table public.rag_chunks enable row level security;

revoke all on public.rag_documents, public.rag_document_revisions, public.rag_chunks
    from anon, authenticated;

grant all on public.rag_documents, public.rag_document_revisions, public.rag_chunks
    to service_role;

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
begin
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
        p_document->>'owner_identity'
    )
    on conflict (canonical_url, source_type) do update
    set title = coalesce(excluded.title, public.rag_documents.title),
        owner_identity = coalesce(excluded.owner_identity, public.rag_documents.owner_identity),
        updated_at = pg_catalog.now()
    returning * into v_document;

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
        on conflict (chunk_id) do update
        set revision_id = excluded.revision_id,
            document_id = excluded.document_id,
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

grant execute on function public.ingest_rag_revision(jsonb, jsonb, jsonb) to service_role;
