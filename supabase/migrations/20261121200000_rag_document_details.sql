-- Return detailed metadata and chunk previews for a user-owned document.
--
-- The owner check prevents a user from inspecting another user's document.
-- Chunk previews are bounded to avoid returning an entire document through
-- the detail endpoint.

create or replace function public.get_rag_document_details(
    p_owner_identity text,
    p_document_id uuid
)
returns jsonb
language sql
security invoker
set search_path = ''
as $$
    with selected_document as (
        select *
        from public.rag_documents
        where document_id = p_document_id
          and owner_identity = p_owner_identity
    ),
    selected_revision as (
        select *
        from public.rag_document_revisions
        where document_id = (select document_id from selected_document)
        order by extracted_at desc, created_at desc
        limit 1
    )
    select jsonb_build_object(
        'document', to_jsonb(document),
        'revision', to_jsonb(revision),
        'chunks', coalesce(
            (
                select jsonb_agg(
                    jsonb_build_object(
                        'chunk_id', chunk.chunk_id,
                        'chunk_index', chunk.chunk_index,
                        'heading_path', chunk.heading_path,
                        'preview', left(chunk.text, 240)
                    ) order by chunk.chunk_index
                )
                from public.rag_chunks chunk
                where chunk.revision_id = revision.revision_id
            ),
            '[]'::jsonb
        )
    )
    from selected_document document
    cross join selected_revision revision
$$;

grant execute on function public.get_rag_document_details(text, uuid)
    to service_role;
