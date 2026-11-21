create table if not exists public.scrape_cache (
    url text not null,
    render_js boolean not null default false,
    include_nav boolean not null default false,
    include_header boolean not null default false,
    include_footer boolean not null default false,
    markdown text not null,
    truncated boolean not null default false,
    created_at timestamptz not null default now(),
    primary key (url, render_js, include_nav, include_header, include_footer)
);

create table if not exists public.developer_usage (
    rapidapi_user text primary key,
    total_scrapes_counted bigint not null default 0,
    total_tokens_counted bigint not null default 0,
    gateway text not null default 'unknown',
    last_mode text not null default 'unspecified',
    updated_at timestamptz not null default now()
);

alter table public.scrape_cache enable row level security;
alter table public.developer_usage enable row level security;
revoke all on public.scrape_cache, public.developer_usage from anon, authenticated;
grant all on public.scrape_cache, public.developer_usage to service_role;

-- Token Tax metering: extend usage counts with per-execution token volume.
-- Existing rows gain the new columns via ALTER; fresh installs get them inline.
alter table public.developer_usage
    add column if not exists total_tokens_counted bigint not null default 0;
alter table public.developer_usage
    add column if not exists gateway text;
alter table public.developer_usage
    add column if not exists last_mode text not null default 'unspecified';

update public.developer_usage
set gateway = 'unknown'
where gateway is null;

update public.developer_usage
set last_mode = 'unspecified'
where last_mode is null;

alter table public.developer_usage
    alter column gateway set default 'unknown',
    alter column gateway set not null,
    alter column last_mode set default 'unspecified',
    alter column last_mode set not null;

create or replace function public.increment_developer_usage(
    p_rapidapi_user text,
    p_gateway text,
    p_scrapes bigint,
    p_tokens bigint,
    p_mode text
)
returns void
language sql
security invoker
set search_path = ''
as $$
    insert into public.developer_usage (
        rapidapi_user, total_scrapes_counted, total_tokens_counted, gateway, last_mode, updated_at
    )
    values (
        p_rapidapi_user,
        greatest(coalesce(p_scrapes, 1), 0),
        greatest(coalesce(p_tokens, 0), 0),
        coalesce(p_gateway, 'unknown'),
        coalesce(p_mode, 'unspecified'),
        pg_catalog.now()
    )
    on conflict (rapidapi_user) do update
    set total_scrapes_counted = public.developer_usage.total_scrapes_counted + excluded.total_scrapes_counted,
        total_tokens_counted = public.developer_usage.total_tokens_counted + excluded.total_tokens_counted,
        gateway = public.developer_usage.gateway,
        last_mode = excluded.last_mode,
        updated_at = pg_catalog.now();
$$;

grant execute on function public.increment_developer_usage(text, text, bigint, bigint, text) to service_role;

-- Keep legacy RPC call shapes working while callers migrate.
create or replace function public.increment_developer_usage(
    p_rapidapi_user text,
    p_tokens bigint
)
returns void
language sql
security invoker
set search_path = ''
as $$
    select public.increment_developer_usage(
        p_rapidapi_user, 'unknown', 1, p_tokens, 'scrape'
    );
$$;

grant execute on function public.increment_developer_usage(text, bigint) to service_role;

create or replace function public.increment_developer_usage(
    p_rapidapi_user text,
    p_tokens bigint,
    p_mode text
)
returns void
language sql
security invoker
set search_path = ''
as $$
    select public.increment_developer_usage(
        p_rapidapi_user, 'unknown', 1, p_tokens, p_mode
    );
$$;

grant execute on function public.increment_developer_usage(text, bigint, text) to service_role;

create or replace function public.increment_developer_usage(p_rapidapi_user text)
returns void
language sql
security invoker
set search_path = ''
as $$
    select public.increment_developer_usage(
        p_rapidapi_user, 'unknown', 1, 1, 'scrape'
    );
$$;

grant execute on function public.increment_developer_usage(text) to service_role;

-- Persistent extraction metadata and version discrimination.
-- Existing/unversioned writers remain legacy; current writers set their version.
alter table public.scrape_cache
    add column if not exists html_tokens bigint not null default 0,
    add column if not exists tokens_saved_estimate bigint not null default 0,
    add column if not exists limiting_factor text not null default 'none',
    add column if not exists extracted_at timestamptz,
    add column if not exists extractor_version text not null default 'legacy';

-- Preserve page provenance across persistent-cache hits.
alter table public.scrape_cache
    add column if not exists page_title text,
    add column if not exists page_title_source text not null default 'none',
    add column if not exists content_fingerprint text;

-- Preserve the source content hash across persistent-cache hits.
alter table public.scrape_cache
    add column if not exists content_hash text;

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
