-- Add optional document scoping to RAG keyword retrieval.
--
-- A document filter is combined with the existing tenant-isolation and
-- access-label conditions. It restricts results further; it never replaces
-- either authorization boundary.

create or replace function public.search_rag_chunks(
    p_query text,
    p_limit integer,
    p_access_labels text[],
    p_owner_identity text,
    p_document_id text default null
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
        select term
        from unnest(
            regexp_split_to_array(
                lower(trim(p_query)),
                '\W+'
            )
        ) as term
        where term <> ''
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
                where lower(chunk.text) ~* ('\m' || query_terms.term || '\M')
                   or exists (
                        select 1
                        from unnest(chunk.heading_path) as heading
                        where lower(heading) ~* ('\m' || query_terms.term || '\M')
                   )
            )::double precision / greatest(
                (select count(*) from query_terms),
                1
            ) as score
        from public.rag_chunks chunk
        join public.rag_documents document
          on document.document_id = chunk.document_id
        where
            (
                p_access_labels is null
                or cardinality(p_access_labels) = 0
                or chunk.access_labels && p_access_labels
            )
            and (
                document.owner_identity is null
                or document.owner_identity = p_owner_identity
            )
            and (
                p_document_id is null
                or chunk.document_id::text = p_document_id
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

grant execute on function public.search_rag_chunks(text, integer, text[], text, text)
    to service_role;
