-- Delete a knowledge document owned by the authenticated user.
--
-- Deleting the document cascades to its revisions and chunks through the
-- existing foreign-key constraints. The owner check prevents a user from
-- deleting another user's document.

create or replace function public.delete_rag_document(
    p_owner_identity text,
    p_document_id uuid
)
returns boolean
language plpgsql
security invoker
set search_path = ''
as $$
declare
    deleted boolean;
begin
    delete from public.rag_documents
    where document_id = p_document_id
      and owner_identity = p_owner_identity
    returning true into deleted;

    return coalesce(deleted, false);
end;
$$;

grant execute on function public.delete_rag_document(text, uuid)
    to service_role;
