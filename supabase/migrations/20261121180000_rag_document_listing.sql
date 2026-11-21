-- List RAG documents owned by the authenticated user.
--
-- The RPC is security invoker and filters strictly by owner identity. It does
-- not expose documents owned by other users.

create or replace function public.list_rag_documents(
    p_owner_identity text,
    p_limit integer default 20,
    p_offset integer default 0
)
returns table (
    document_id uuid,
    canonical_url text,
    title text,
    source_type text,
    created_at timestamptz,
    updated_at timestamptz,
    revision_count bigint,
    total bigint
)
language sql
security invoker
set search_path = ''
as $$
    select
        document.document_id,
        document.canonical_url,
        document.title,
        document.source_type,
        document.created_at,
        document.updated_at,
        count(revision.revision_id)::bigint as revision_count,
        count(*) over ()::bigint as total
    from public.rag_documents document
    left join public.rag_document_revisions revision
      on revision.document_id = document.document_id
    where document.owner_identity = p_owner_identity
    group by
        document.document_id,
        document.canonical_url,
        document.title,
        document.source_type,
        document.created_at,
        document.updated_at
    order by document.updated_at desc, document.document_id asc
    limit greatest(coalesce(p_limit, 20), 1)
    offset greatest(coalesce(p_offset, 0), 0);
$$;

grant execute on function public.list_rag_documents(text, integer, integer)
    to service_role;
