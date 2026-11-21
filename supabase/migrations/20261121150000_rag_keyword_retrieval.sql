-- Keyword retrieval baseline for the RAG knowledge core.

create or replace function public.search_rag_chunks(
    p_query text,
    p_limit integer,
    p_access_labels text[],
    p_owner_identity text
)
returns table (
    chunk_id text,
    revision_id uuid,
    document_id uuid,
    text text,
    score double precision,
    source_url text,
    final_url text,
    heading_path text[],
    access_labels text[]
)
language sql
security invoker
set search_path = ''
as $$
    with query_terms as (
        select unnest(
            string_to_array(
                lower(trim(p_query)),
                ' '
            )
        ) as term
        where nullif(trim(p_query), '') is not null
    ),
    scored_chunks as (
        select
            chunk.chunk_id,
            chunk.revision_id,
            chunk.document_id,
            chunk.text,
            chunk.source_url,
            chunk.final_url,
            chunk.heading_path,
            chunk.access_labels,
            (
                select count(*)
                from query_terms
                where position(query_terms.term in lower(chunk.text)) > 0
                   or exists (
                        select 1
                        from unnest(chunk.heading_path) as heading
                        where position(query_terms.term in lower(heading)) > 0
                   )
            )::double precision / greatest(
                (select count(*) from query_terms),
                1
            ) as score
        from public.rag_chunks chunk
        where
            (
                p_access_labels is null
                or chunk.access_labels && p_access_labels
            )
            and (
                p_owner_identity is null
                or chunk.owner_identity is null
                or chunk.owner_identity = p_owner_identity
            )
    )
    select
        chunk_id,
        revision_id,
        document_id,
        text,
        score,
        source_url,
        final_url,
        heading_path,
        access_labels
    from scored_chunks
    where score > 0
    order by score desc, chunk_id asc
    limit greatest(coalesce(p_limit, 8), 1);
$$;

grant execute on function public.search_rag_chunks(text, integer, text[], text)
    to service_role;
